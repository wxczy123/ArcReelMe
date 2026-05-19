"""角色管理路由（基础 CRUD 由 _asset_router_factory 统一生成，形态接口单独补充）。"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import File, HTTPException, UploadFile
from pydantic import BaseModel

from lib.app_data_dir import app_data_dir
from lib.character_assets import validate_form_id, validate_ref_slot
from lib.i18n import Translator
from lib.image_utils import normalize_uploaded_image
from lib.project_change_hints import project_change_source
from lib.project_manager import ProjectManager
from server.auth import CurrentUser
from server.routers._asset_router_factory import build_asset_router

pm = ProjectManager(app_data_dir())


def get_project_manager() -> ProjectManager:
    return pm


# late-binding 必需：测试通过 monkeypatch.setattr(characters, "get_project_manager", ...) 替换模块属性
router = build_asset_router(asset_type="character", pm_getter=lambda: get_project_manager())  # noqa: PLW0108


class CharacterFormCreateRequest(BaseModel):
    form_id: str
    label: str = ""
    description: str = ""


class CharacterFormUpdateRequest(BaseModel):
    label: str | None = None
    description: str | None = None
    storyboard_ref_slot: str | None = None
    default_form: bool | None = None


class CharacterInputRefDeleteRequest(BaseModel):
    path: str


@router.post("/projects/{project_name}/characters/{char_name}/forms")
async def add_character_form(
    project_name: str,
    char_name: str,
    req: CharacterFormCreateRequest,
    _user: CurrentUser,
    _t: Translator,
):
    try:

        def _sync():
            with project_change_source("webui"):
                project = get_project_manager().add_character_form(
                    project_name,
                    char_name,
                    req.form_id,
                    label=req.label,
                    description=req.description,
                )
            return {"success": True, "character": project["characters"][char_name]}

        return await asyncio.to_thread(_sync)
    except KeyError:
        raise HTTPException(status_code=404, detail=_t("character_not_found", name=char_name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name))


@router.patch("/projects/{project_name}/characters/{char_name}/forms/{form_id}")
async def update_character_form(
    project_name: str,
    char_name: str,
    form_id: str,
    req: CharacterFormUpdateRequest,
    _user: CurrentUser,
    _t: Translator,
):
    try:

        def _sync():
            with project_change_source("webui"):
                project = get_project_manager().update_character_form(
                    project_name,
                    char_name,
                    form_id,
                    label=req.label,
                    description=req.description,
                    storyboard_ref_slot=req.storyboard_ref_slot,
                )
                if req.default_form:
                    project = get_project_manager().update_character_default_form(project_name, char_name, form_id)
            return {"success": True, "character": project["characters"][char_name]}

        return await asyncio.to_thread(_sync)
    except KeyError:
        raise HTTPException(status_code=404, detail=_t("character_not_found", name=char_name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name))


@router.delete("/projects/{project_name}/characters/{char_name}/forms/{form_id}")
async def delete_character_form(
    project_name: str,
    char_name: str,
    form_id: str,
    _user: CurrentUser,
    _t: Translator,
):
    try:

        def _sync():
            with project_change_source("webui"):
                project = get_project_manager().delete_character_form(project_name, char_name, form_id)
            return {"success": True, "character": project["characters"][char_name]}

        return await asyncio.to_thread(_sync)
    except KeyError:
        raise HTTPException(status_code=404, detail=_t("character_not_found", name=char_name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name))


@router.post("/projects/{project_name}/characters/{char_name}/forms/{form_id}/refs/{slot}")
async def upload_character_form_ref(
    project_name: str,
    char_name: str,
    form_id: str,
    slot: str,
    _user: CurrentUser,
    _t: Translator,
    file: UploadFile = File(...),
):
    """上传某形态的最终参考图槽位。"""
    try:
        form_id = validate_form_id(form_id)
        slot = validate_ref_slot(slot)
        original_ext = Path(file.filename or "").suffix.lower()
        content = await file.read()
        content, ext = normalize_uploaded_image(content, original_ext)

        def _sync():
            project_dir = get_project_manager().get_project_path(project_name)
            target_rel = f"characters/{char_name}/{form_id}/{slot}{ext}"
            target_path = project_dir / target_rel
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(content)
            with project_change_source("webui"):
                project = get_project_manager().update_character_ref_path(
                    project_name,
                    char_name,
                    form_id,
                    slot,
                    target_rel,
                )
            return {
                "success": True,
                "path": target_rel,
                "url": f"/api/v1/files/{project_name}/{target_rel}",
                "character": project["characters"][char_name],
            }

        return await asyncio.to_thread(_sync)
    except KeyError:
        raise HTTPException(status_code=404, detail=_t("character_not_found", name=char_name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name))


@router.post("/projects/{project_name}/characters/{char_name}/forms/{form_id}/input-refs")
async def upload_character_input_ref(
    project_name: str,
    char_name: str,
    form_id: str,
    _user: CurrentUser,
    _t: Translator,
    file: UploadFile = File(...),
):
    """上传某形态的生成输入参考图。"""
    try:
        form_id = validate_form_id(form_id)
        original_ext = Path(file.filename or "").suffix.lower()
        content = await file.read()
        content, ext = normalize_uploaded_image(content, original_ext)
        filename = f"{uuid.uuid4().hex}{ext}"

        def _sync():
            project_dir = get_project_manager().get_project_path(project_name)
            target_rel = f"characters/{char_name}/{form_id}/input_refs/{filename}"
            target_path = project_dir / target_rel
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(content)
            with project_change_source("webui"):
                project = get_project_manager().add_character_input_ref(project_name, char_name, form_id, target_rel)
            return {
                "success": True,
                "path": target_rel,
                "url": f"/api/v1/files/{project_name}/{target_rel}",
                "character": project["characters"][char_name],
            }

        return await asyncio.to_thread(_sync)
    except KeyError:
        raise HTTPException(status_code=404, detail=_t("character_not_found", name=char_name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name))


@router.delete("/projects/{project_name}/characters/{char_name}/forms/{form_id}/input-refs")
async def delete_character_input_ref(
    project_name: str,
    char_name: str,
    form_id: str,
    _user: CurrentUser,
    _t: Translator,
    req: CharacterInputRefDeleteRequest,
):
    """删除某形态的生成输入参考图。"""
    try:
        form_id = validate_form_id(form_id)
        if not req.path:
            raise ValueError("path is required")

        def _sync():
            project_dir = get_project_manager().get_project_path(project_name)
            target_path = project_dir / req.path
            try:
                target_path.resolve().relative_to(project_dir.resolve())
            except ValueError:
                raise HTTPException(status_code=403, detail=_t("forbidden_access"))

            if target_path.exists():
                target_path.unlink()
            with project_change_source("webui"):
                project = get_project_manager().remove_character_input_ref(
                    project_name,
                    char_name,
                    form_id,
                    req.path,
                )
            return {
                "success": True,
                "path": req.path,
                "character": project["characters"][char_name],
            }

        return await asyncio.to_thread(_sync)
    except KeyError:
        raise HTTPException(status_code=404, detail=_t("character_not_found", name=char_name))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=_t("project_not_found", name=project_name))
