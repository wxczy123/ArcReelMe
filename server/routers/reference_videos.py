"""参考生视频 CRUD + 生成路由。

Mount prefix: /api/v1/projects/{project_name}/reference-videos
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field, model_validator

from lib.app_data_dir import app_data_dir
from lib.asset_types import BUCKET_KEY
from lib.character_assets import DEFAULT_FORM_ID, ensure_character_forms, validate_form_id
from lib.generation_queue import get_generation_queue
from lib.i18n import Translator
from lib.project_change_hints import emit_project_change_batch
from lib.project_manager import EpisodeScriptReboundError, ProjectManager, effective_mode
from lib.reference_video import parse_prompt
from lib.thumbnail import extract_video_thumbnail
from lib.version_manager import VersionManager
from server.auth import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/projects/{project_name}/reference-videos",
    tags=["reference-videos"],
)

pm = ProjectManager(app_data_dir())


def get_project_manager() -> ProjectManager:
    return pm


# ============ 请求模型 ============


class ReferenceDto(BaseModel):
    type: str = Field(pattern=r"^(character|scene|prop)$")
    name: str
    form_id: str | None = None

    @model_validator(mode="after")
    def _validate_form_id_scope(self) -> ReferenceDto:
        if not self.form_id:
            self.form_id = None
            return self
        if self.type != "character":
            raise ValueError("form_id 仅适用于 character reference")
        self.form_id = validate_form_id(self.form_id)
        return self


class AddUnitRequest(BaseModel):
    prompt: str
    references: list[ReferenceDto] = Field(default_factory=list)
    duration_seconds: int | None = None
    transition_to_next: str = Field(default="cut", pattern=r"^(cut|fade|dissolve)$")
    note: str | None = None


# ============ 辅助 ============


def _load_episode_script(project_name: str, episode: int, _t: Translator) -> tuple[dict, dict, str]:
    """加载 project.json + 指定集的剧本。返回 (project, script, script_file)。"""
    try:
        project = get_project_manager().load_project(project_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name)) from exc
    episodes = project.get("episodes") or []
    meta = next((e for e in episodes if e.get("episode") == episode), None)
    if meta is None or not meta.get("script_file"):
        raise HTTPException(status_code=404, detail=_t("ref_episode_not_found", episode=episode))
    script_file = meta["script_file"]
    try:
        script = get_project_manager().load_script(project_name, script_file)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_t("script_not_found", name=script_file)) from exc
    if effective_mode(project=project, episode=meta) != "reference_video":
        raise HTTPException(status_code=409, detail=_t("ref_not_reference_video_mode"))
    return project, script, script_file


def _episode_script_resolver(episode: int, _t: Translator, refs: list[dict] | None = None) -> Callable[[dict], str]:
    """构造一个解析器：从 project.json 解析并校验指定集，返回其 script_file。

    解析器在 `locked_episode_script` 的项目锁内被调用（候选解析 + 持锁复核各一次），
    把「找 episode + reference_video 模式校验 + 可选 references 存在性校验」收进同一临界区，
    避免锁外快照与并发写者不一致。
    """

    def _resolve(project: dict) -> str:
        episodes = project.get("episodes") or []
        meta = next((e for e in episodes if e.get("episode") == episode), None)
        if meta is None or not meta.get("script_file"):
            raise HTTPException(status_code=404, detail=_t("ref_episode_not_found", episode=episode))
        if effective_mode(project=project, episode=meta) != "reference_video":
            raise HTTPException(status_code=409, detail=_t("ref_not_reference_video_mode"))
        if refs is not None:
            _validate_references_exist(project, refs, _t)
        return meta["script_file"]

    return _resolve


@contextmanager
def _locked_episode_script(project_name: str, resolver: Callable[[dict], str], _t: Translator) -> Iterator[dict]:
    """进入 `locked_episode_script`，把缺失文件归一为 404、并发改绑归一为 409。

    project.json 可能残留指向已删除/移动文件的 script_file；此时锁内 load_script 抛
    FileNotFoundError，需转成 404 而非 500。加锁前后 episode→script_file 绑定被并发 PATCH
    改动时抛 EpisodeScriptReboundError，转成 409（前端可重试，不外泄内部绑定细节）。
    """
    try:
        with get_project_manager().locked_episode_script(project_name, resolver) as script:
            yield script
    except FileNotFoundError as exc:
        # 区分「项目缺失」与「project.json 指向的脚本文件缺失（stale 绑定）」
        if not get_project_manager().project_exists(project_name):
            raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name)) from exc
        raise HTTPException(status_code=404, detail=_t("ref_script_missing")) from exc
    except EpisodeScriptReboundError as exc:
        logger.info("episode script rebound during write: %s", exc)
        raise HTTPException(status_code=409, detail=_t("ref_script_rebound")) from exc


def _validate_references_exist(project: dict, refs: list[dict], _t: Translator) -> None:
    """确保 references 都在 project.json 对应 bucket 中。"""
    missing: list[str] = []
    invalid_forms: list[str] = []
    for r in refs:
        bucket = project.get(BUCKET_KEY.get(r["type"], "")) or {}
        if r["name"] not in bucket:
            missing.append(f"{r['type']}:{r['name']}")
            continue
        if r["type"] == "character":
            char_data = bucket.get(r["name"])
            if isinstance(char_data, dict):
                normalized = ensure_character_forms(dict(char_data))
                form_id = r.get("form_id") or normalized.get("default_form") or DEFAULT_FORM_ID
                if form_id not in (normalized.get("forms") or {}):
                    invalid_forms.append(f"character:{r['name']}/{form_id}")
        elif r.get("form_id"):
            invalid_forms.append(f"{r['type']}:{r['name']} 不应包含 form_id")
    if missing:
        raise HTTPException(status_code=400, detail=_t("ref_not_registered", missing=", ".join(missing)))
    if invalid_forms:
        raise HTTPException(
            status_code=400,
            detail=f"references form_id invalid: {', '.join(invalid_forms)}",
        )


def _next_unit_id(script: dict, episode: int) -> str:
    existing = {str(u.get("unit_id", "")) for u in (script.get("video_units") or [])}
    idx = 1
    while f"E{episode}U{idx}" in existing:
        idx += 1
    return f"E{episode}U{idx}"


def _build_unit_dict(
    *,
    unit_id: str,
    prompt: str,
    references: list[dict],
    duration_override: int | None,
    transition: str,
    note: str | None,
) -> dict:
    shots, _names, override = parse_prompt(prompt)
    if override and duration_override is not None:
        shots[0].duration = max(1, int(duration_override))
    duration_total = sum(s.duration for s in shots)
    return {
        "unit_id": unit_id,
        "shots": [s.model_dump() for s in shots],
        "references": references,
        "duration_seconds": duration_total,
        "duration_override": override,
        "transition_to_next": transition,
        "note": note,
        "generated_assets": {
            "storyboard_image": None,
            "storyboard_last_image": None,
            "grid_id": None,
            "grid_cell_index": None,
            "video_clip": None,
            "video_uri": None,
            "status": "pending",
        },
    }


def _unit_asset_fingerprints(project_path: Path, unit_id: str) -> dict[str, int]:
    paths = {
        f"reference_videos/{unit_id}.mp4": project_path / "reference_videos" / f"{unit_id}.mp4",
        f"reference_videos/thumbnails/{unit_id}.jpg": project_path / "reference_videos" / "thumbnails" / f"{unit_id}.jpg",
    }
    return {rel: path.stat().st_mtime_ns for rel, path in paths.items() if path.exists()}


def _backfill_existing_unit_videos(project_path: Path, script: dict) -> bool:
    """用磁盘上的已生成视频补齐旧剧本里缺失的 generated_assets。

    这覆盖一种实际脏数据：任务第二次已经生成了 reference_videos/E1Uxx.mp4，
    但旧 failed 队列状态或历史写回问题导致 JSON 里仍没有 video_clip。
    """
    changed = False
    for unit in script.get("video_units") or []:
        if not isinstance(unit, dict):
            continue
        unit_id = str(unit.get("unit_id") or "").strip()
        if not unit_id:
            continue

        video_rel = f"reference_videos/{unit_id}.mp4"
        video_path = project_path / "reference_videos" / f"{unit_id}.mp4"
        if not video_path.exists():
            continue

        assets = unit.get("generated_assets")
        if not isinstance(assets, dict):
            assets = {}
            unit["generated_assets"] = assets
            changed = True

        if assets.get("video_clip") != video_rel:
            assets["video_clip"] = video_rel
            changed = True
        if assets.get("status") != "completed":
            assets["status"] = "completed"
            changed = True

        thumb_rel = f"reference_videos/thumbnails/{unit_id}.jpg"
        thumb_path = project_path / "reference_videos" / "thumbnails" / f"{unit_id}.jpg"
        if thumb_path.exists() and assets.get("video_thumbnail") != thumb_rel:
            assets["video_thumbnail"] = thumb_rel
            changed = True

    return changed


def _emit_unit_video_ready(project_name: str, episode: int, unit_id: str, fingerprints: dict[str, int]) -> None:
    change = {
        "entity_type": "reference_video_unit",
        "action": "reference_video_ready",
        "entity_id": unit_id,
        "label": f"参考视频「{unit_id}」",
        "focus": None,
        "important": True,
        "episode": episode,
        "asset_fingerprints": fingerprints,
    }
    try:
        emit_project_change_batch(project_name, [change], source="webui")
    except Exception:
        logger.warning("发送参考视频上传事件失败 project=%s episode=%s unit=%s", project_name, episode, unit_id, exc_info=True)


# ============ 端点：列出 + 新建 ============


@router.get("/episodes/{episode}/units")
async def list_units(project_name: str, episode: int, _user: CurrentUser, _t: Translator) -> dict[str, Any]:
    _project, script, _sf = _load_episode_script(project_name, episode, _t)
    project_path = get_project_manager().get_project_path(project_name)
    if _backfill_existing_unit_videos(project_path, script):
        with _locked_episode_script(project_name, _episode_script_resolver(episode, _t), _t) as fresh_script:
            _backfill_existing_unit_videos(project_path, fresh_script)
            script = fresh_script
    return {"units": script.get("video_units") or []}


@router.post("/episodes/{episode}/units", status_code=status.HTTP_201_CREATED)
async def add_unit(
    project_name: str,
    episode: int,
    req: AddUnitRequest,
    _user: CurrentUser,
    _t: Translator,
) -> dict[str, Any]:
    refs = [r.model_dump(exclude_none=True) for r in req.references]

    with _locked_episode_script(project_name, _episode_script_resolver(episode, _t, refs), _t) as script:
        # unit_id 在锁内基于 fresh script 计算，避免并发新增撞 ID
        unit = _build_unit_dict(
            unit_id=_next_unit_id(script, episode),
            prompt=req.prompt,
            references=refs,
            duration_override=req.duration_seconds,
            transition=req.transition_to_next,
            note=req.note,
        )
        script.setdefault("video_units", []).append(unit)
    return {"unit": unit}


# ============ 端点：PATCH + DELETE ============


class PatchUnitRequest(BaseModel):
    prompt: str | None = None
    references: list[ReferenceDto] | None = None
    duration_seconds: int | None = None
    transition_to_next: str | None = Field(default=None, pattern=r"^(cut|fade|dissolve)$")
    note: str | None = None


def _find_unit(script: dict, unit_id: str, _t: Translator) -> dict:
    for u in script.get("video_units") or []:
        if u.get("unit_id") == unit_id:
            return u
    raise HTTPException(status_code=404, detail=_t("ref_unit_not_found", unit_id=unit_id))


@router.patch("/episodes/{episode}/units/{unit_id}")
async def patch_unit(
    project_name: str,
    episode: int,
    unit_id: str,
    req: PatchUnitRequest,
    _user: CurrentUser,
    _t: Translator,
) -> dict[str, Any]:
    # references 存在性校验在解析器内、项目锁内进行，失败 raise 400
    refs: list[dict] | None = (
        [r.model_dump(exclude_none=True) for r in req.references] if req.references is not None else None
    )

    with _locked_episode_script(project_name, _episode_script_resolver(episode, _t, refs), _t) as script:
        unit = _find_unit(script, unit_id, _t)  # 未找到 raise 404 → 跳过写回

        if refs is not None:
            unit["references"] = refs

        if req.prompt is not None:
            shots, _mentions, override = parse_prompt(req.prompt)
            if override and req.duration_seconds is not None:
                shots[0].duration = max(1, int(req.duration_seconds))
            unit["shots"] = [s.model_dump() for s in shots]
            unit["duration_seconds"] = sum(s.duration for s in shots)
            unit["duration_override"] = override
        elif req.duration_seconds is not None and unit.get("duration_override"):
            unit["duration_seconds"] = max(1, int(req.duration_seconds))
            if unit.get("shots"):
                unit["shots"][0]["duration"] = unit["duration_seconds"]

        if req.transition_to_next is not None:
            unit["transition_to_next"] = req.transition_to_next
        if req.note is not None:
            unit["note"] = req.note

    return {"unit": unit}


@router.delete("/episodes/{episode}/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_unit(
    project_name: str,
    episode: int,
    unit_id: str,
    _user: CurrentUser,
    _t: Translator,
) -> Response:
    with _locked_episode_script(project_name, _episode_script_resolver(episode, _t), _t) as script:
        units = script.get("video_units") or []
        new_units = [u for u in units if u.get("unit_id") != unit_id]
        if len(new_units) == len(units):
            # 未找到 → 在锁内 raise，跳过写回
            raise HTTPException(status_code=404, detail=_t("ref_unit_not_found", unit_id=unit_id))
        script["video_units"] = new_units
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class ReorderRequest(BaseModel):
    unit_ids: list[str]


@router.post("/episodes/{episode}/units/reorder")
async def reorder_units(
    project_name: str,
    episode: int,
    req: ReorderRequest,
    _user: CurrentUser,
    _t: Translator,
) -> dict[str, Any]:
    with _locked_episode_script(project_name, _episode_script_resolver(episode, _t), _t) as script:
        units = script.get("video_units") or []
        existing_ids = [u.get("unit_id") for u in units]

        # 校验失败 → 在锁内 raise 400，跳过写回
        if len(req.unit_ids) != len(existing_ids):
            raise HTTPException(status_code=400, detail=_t("ref_unit_ids_length_mismatch"))
        if len(set(req.unit_ids)) != len(req.unit_ids):
            raise HTTPException(status_code=400, detail=_t("ref_duplicate_unit_ids"))
        if set(req.unit_ids) != set(existing_ids):
            raise HTTPException(status_code=400, detail=_t("ref_unit_ids_mismatch"))

        by_id = {u["unit_id"]: u for u in units}
        reordered = [by_id[uid] for uid in req.unit_ids]
        script["video_units"] = reordered
    return {"units": reordered}


@router.post(
    "/episodes/{episode}/units/{unit_id}/generate",
    status_code=status.HTTP_202_ACCEPTED,
)
async def generate_unit(
    project_name: str,
    episode: int,
    unit_id: str,
    _user: CurrentUser,
    _t: Translator,
) -> dict[str, Any]:
    _project, script, script_file = _load_episode_script(project_name, episode, _t)
    _find_unit(script, unit_id, _t)  # raises 404 if missing

    queue = get_generation_queue()
    result = await queue.enqueue_task(
        project_name=project_name,
        task_type="reference_video",
        media_type="video",
        resource_id=unit_id,
        payload={"script_file": script_file},
        script_file=script_file,
        source="webui",
        user_id=_user.id,
    )
    return {"task_id": result["task_id"], "deduped": result.get("deduped", False)}


@router.post("/episodes/{episode}/units/{unit_id}/upload")
async def upload_unit_video(
    project_name: str,
    episode: int,
    unit_id: str,
    _user: CurrentUser,
    _t: Translator,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail=_t("missing_filename"))
    ext = Path(file.filename).suffix.lower()
    if ext != ".mp4":
        raise HTTPException(status_code=400, detail=_t("unsupported_video_type", ext=ext, allowed=".mp4"))

    _project, _script, _script_file = _load_episode_script(project_name, episode, _t)
    _find_unit(_script, unit_id, _t)

    try:
        content = await file.read()

        def _store_video() -> tuple[Path, Path, int]:
            project_path = get_project_manager().get_project_path(project_name)
            video_dir = project_path / "reference_videos"
            thumb_dir = video_dir / "thumbnails"
            video_dir.mkdir(parents=True, exist_ok=True)
            thumb_dir.mkdir(parents=True, exist_ok=True)

            output_path = video_dir / f"{unit_id}.mp4"
            versions = VersionManager(project_path)
            if output_path.exists():
                versions.ensure_current_tracked(
                    "reference_videos",
                    unit_id,
                    output_path,
                    "手动上传前版本",
                    source="manual_upload_existing",
                )
            output_path.write_bytes(content)
            version = versions.add_version(
                "reference_videos",
                unit_id,
                "手动上传视频",
                source_file=output_path,
                source="manual_upload",
                original_filename=file.filename,
            )
            return project_path, output_path, version

        project_path, output_path, version = await asyncio.to_thread(_store_video)

        thumb_path = project_path / "reference_videos" / "thumbnails" / f"{unit_id}.jpg"
        thumb_rel: str | None = None
        if await extract_video_thumbnail(output_path, thumb_path):
            thumb_rel = f"reference_videos/thumbnails/{unit_id}.jpg"
        else:
            thumb_path.unlink(missing_ok=True)

        def _update_script() -> dict[str, Any]:
            with _locked_episode_script(project_name, _episode_script_resolver(episode, _t), _t) as script:
                unit = _find_unit(script, unit_id, _t)
                ga = unit.setdefault("generated_assets", {})
                ga["video_clip"] = f"reference_videos/{unit_id}.mp4"
                ga.pop("video_uri", None)
                if thumb_rel:
                    ga["video_thumbnail"] = thumb_rel
                else:
                    ga.pop("video_thumbnail", None)
                ga["status"] = "completed"
                return unit

        updated_unit = await asyncio.to_thread(_update_script)
        result = {
            "unit": updated_unit,
            "file_path": f"reference_videos/{unit_id}.mp4",
            "version": version,
            "asset_fingerprints": _unit_asset_fingerprints(project_path, unit_id),
        }
        _emit_unit_video_ready(project_name, episode, unit_id, result.get("asset_fingerprints") or {})
        return result
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name)) from exc
