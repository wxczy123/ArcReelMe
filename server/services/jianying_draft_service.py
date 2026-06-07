"""剪映草稿导出服务

将 ArcReel 单集已生成的视频片段导出为剪映草稿 ZIP。
使用 pyJianYingDraft 库生成 draft_content.json，
后处理路径替换使草稿指向用户本地剪映目录。
"""

import json
import logging
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

import pyJianYingDraft as draft
from pyJianYingDraft import (
    ClipSettings,
    TextBorder,
    TextSegment,
    TextShadow,
    TextStyle,
    TrackType,
    TransitionType,
    VideoMaterial,
    VideoSegment,
    trange,
)

# transition_to_next schema 值 → 剪映 TransitionType。"cut" 不挂转场。
_TRANSITION_MAP: dict[str, TransitionType] = {
    "fade": TransitionType.闪黑,
    "dissolve": TransitionType.叠化,
}

from lib.project_manager import ProjectManager

logger = logging.getLogger(__name__)


class JianyingDraftService:
    """剪映草稿导出服务"""

    def __init__(self, project_manager: ProjectManager):
        self.pm = project_manager

    @staticmethod
    def _normalize_user_path(path: str) -> str:
        """剪映草稿 JSON 内统一使用 Windows 可识别的正斜杠路径。"""
        return path.strip().replace("\\", "/").rstrip("/")

    @classmethod
    def _join_user_path(cls, base_path: str, *parts: str) -> str:
        cleaned_base = cls._normalize_user_path(base_path)
        cleaned_parts = [part.strip("/\\") for part in parts if part.strip("/\\")]
        if not cleaned_parts:
            return cleaned_base
        return "/".join([cleaned_base, *cleaned_parts])

    # ------------------------------------------------------------------
    # 内部方法：数据提取
    # ------------------------------------------------------------------

    def _find_episode_script(self, project_name: str, project: dict, episode: int) -> tuple[dict, str]:
        """定位指定集的剧本文件，返回 (script_dict, filename)"""
        episodes = project.get("episodes", [])
        ep_entry = next((e for e in episodes if e.get("episode") == episode), None)
        if ep_entry is None:
            raise FileNotFoundError(f"第 {episode} 集不存在")

        script_file = ep_entry.get("script_file", "")
        filename = Path(script_file).name
        script_data = self.pm.load_script(project_name, filename)
        return script_data, filename

    def _collect_video_clips(self, script: dict, project_dir: Path) -> list[dict[str, Any]]:
        """从剧本中提取已完成视频的片段列表"""
        project_root = project_dir.resolve()
        if script.get("generation_mode") == "reference_video":
            return [
                clip
                for item in script.get("video_units", [])
                if (clip := self._clip_from_item(item, project_dir, project_root=project_root, id_field="unit_id"))
                is not None
            ]

        content_mode = script.get("content_mode", "narration")
        items = script.get("segments" if content_mode == "narration" else "scenes", [])
        id_field = "segment_id" if content_mode == "narration" else "scene_id"

        clips = []
        for item in items:
            clip = self._clip_from_item(item, project_dir, project_root=project_root, id_field=id_field)
            if clip is not None:
                clips.append(clip)

        return clips

    def _clip_from_item(
        self,
        item: dict[str, Any],
        project_dir: Path,
        *,
        project_root: Path,
        id_field: str,
    ) -> dict[str, Any] | None:
        assets = item.get("generated_assets") or {}
        video_clip = assets.get("video_clip")
        if not video_clip:
            return None

        abs_path = (project_dir / video_clip).resolve()
        if not abs_path.is_relative_to(project_root):
            logger.warning("video_clip 路径越界，已跳过: %s", video_clip)
            return None
        if not abs_path.exists():
            return None

        return {
            "id": item.get(id_field, ""),
            "duration_seconds": item.get("duration_seconds", 8),
            "video_clip": video_clip,
            "abs_path": abs_path,
            "novel_text": item.get("novel_text", ""),
            "transition_to_next": item.get("transition_to_next", "cut"),
        }

    def _resolve_canvas_size(self, project: dict, first_video_path: Path | None = None) -> tuple[int, int]:
        """根据项目 aspect_ratio 确定画布尺寸，缺失时从首个视频自动检测"""
        ar = project.get("aspect_ratio")
        aspect = ar if isinstance(ar, str) else (ar.get("video") if isinstance(ar, dict) else None)
        if aspect is None and first_video_path is not None:
            mat = VideoMaterial(str(first_video_path))
            aspect = "9:16" if mat.height > mat.width else "16:9"
        if aspect == "9:16":
            return 1080, 1920
        return 1920, 1080

    # ------------------------------------------------------------------
    # 内部方法：草稿生成
    # ------------------------------------------------------------------

    def _generate_draft(
        self,
        *,
        draft_dir: Path,
        draft_name: str,
        clips: list[dict],
        width: int,
        height: int,
        content_mode: str,
    ) -> None:
        """使用 pyJianYingDraft 在 draft_dir 中生成草稿文件"""
        draft_dir.parent.mkdir(parents=True, exist_ok=True)
        folder = draft.DraftFolder(str(draft_dir.parent))
        script_file = folder.create_draft(draft_name, width=width, height=height, allow_replace=True)

        # 视频轨
        script_file.add_track(TrackType.video)

        # 字幕轨（仅 narration 模式）
        has_subtitle = content_mode == "narration"
        text_style: TextStyle | None = None
        text_border: TextBorder | None = None
        text_shadow: TextShadow | None = None
        subtitle_position: ClipSettings | None = None
        is_portrait = height > width
        if has_subtitle:
            script_file.add_track(TrackType.text, "字幕")
            text_style = TextStyle(
                size=12.0 if is_portrait else 8.0,
                color=(1.0, 1.0, 1.0),
                align=1,
                bold=True,
                auto_wrapping=True,
                max_line_width=0.82 if is_portrait else 0.6,
            )
            text_border = TextBorder(
                color=(0.0, 0.0, 0.0),
                width=30.0,
            )
            text_shadow = TextShadow(
                color=(0.0, 0.0, 0.0),
                alpha=0.7,
                diffuse=8.0,
                distance=3.0,
                angle=-45.0,
            )
            subtitle_position = ClipSettings(
                transform_y=-0.75 if is_portrait else -0.8,
            )

        # 逐片段添加
        offset_us = 0
        last_index = len(clips) - 1
        for index, clip in enumerate(clips):
            # 预读实际视频时长
            material = VideoMaterial(clip["local_path"])
            actual_duration_us = material.duration

            # 视频片段
            video_seg = VideoSegment(
                material,
                trange(offset_us, actual_duration_us),
            )

            # 转场：剪映约定挂在前一段上，因此最后一段不挂；cut 不挂。
            if index < last_index:
                transition_type = _TRANSITION_MAP.get(clip.get("transition_to_next", "cut"))
                if transition_type is not None:
                    video_seg.add_transition(transition_type)

            script_file.add_segment(video_seg)

            # 字幕片段
            if has_subtitle and clip.get("novel_text"):
                text_seg = TextSegment(
                    text=clip["novel_text"],
                    timerange=trange(offset_us, actual_duration_us),
                    style=text_style,
                    border=text_border,
                    shadow=text_shadow,
                    clip_settings=subtitle_position,
                )
                script_file.add_segment(text_seg)

            offset_us += actual_duration_us

        script_file.save()

    def _replace_paths_in_draft(self, *, json_path: Path, tmp_prefix: str, target_prefix: str) -> None:
        """JSON 安全地替换 draft_content.json 中的临时路径"""
        real = os.path.realpath(json_path)
        tmp = os.path.realpath(tempfile.gettempdir()) + os.sep
        if not real.startswith(tmp):
            raise ValueError(f"路径越界，拒绝写入: {real}")

        with open(real, encoding="utf-8") as f:  # noqa: PTH123
            data = json.load(f)

        def _walk(obj: Any) -> Any:
            if isinstance(obj, str) and tmp_prefix in obj:
                return obj.replace(tmp_prefix, target_prefix)
            if isinstance(obj, dict):
                return {k: _walk(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_walk(v) for v in obj]
            return obj

        data = _walk(data)
        with open(real, "w", encoding="utf-8") as f:  # noqa: PTH123
            json.dump(data, f, ensure_ascii=False)

    @staticmethod
    def _build_meta_material_entry(video: dict[str, Any], now_us: int) -> dict[str, Any]:
        now_s = now_us // 1_000_000
        return {
            "ai_group_type": "",
            "create_time": now_s,
            "duration": int(video.get("duration") or 0),
            "extra_info": video.get("material_name") or Path(video.get("path", "")).name,
            "file_Path": video.get("path", ""),
            "height": int(video.get("height") or 0),
            "id": video.get("id") or video.get("material_id") or uuid.uuid4().hex,
            "import_time": now_s,
            "import_time_ms": now_us,
            "item_source": 1,
            "md5": "",
            "metetype": video.get("type") or "video",
            "roughcut_time_range": {
                "duration": -1,
                "start": -1,
            },
            "sub_time_range": {
                "duration": -1,
                "start": -1,
            },
            "type": 0,
            "width": int(video.get("width") or 0),
        }

    @classmethod
    def _sync_meta_materials(cls, meta: dict[str, Any], content: dict[str, Any], now_us: int) -> None:
        """让 draft_meta_info.json 的素材库登记与 draft_content.json 保持同步。"""
        videos = content.get("materials", {}).get("videos", [])
        video_entries = [
            cls._build_meta_material_entry(video, now_us)
            for video in videos
            if isinstance(video, dict) and video.get("path")
        ]

        draft_materials = meta.get("draft_materials")
        if not isinstance(draft_materials, list):
            draft_materials = [{"type": item_type, "value": []} for item_type in (0, 1, 2, 3, 6, 7, 8)]

        video_bucket = next(
            (
                item
                for item in draft_materials
                if isinstance(item, dict) and item.get("type") == 0
            ),
            None,
        )
        if video_bucket is None:
            video_bucket = {"type": 0, "value": []}
            draft_materials.insert(0, video_bucket)

        video_bucket["value"] = video_entries
        meta["draft_materials"] = draft_materials

    def _finalize_draft_metadata(self, *, draft_dir: Path, draft_name: str, draft_path: str) -> None:
        """补齐剪映扫描草稿列表需要的元信息。"""
        now_us = int(time.time() * 1_000_000)
        draft_fold_path = self._normalize_user_path(draft_path)
        draft_root = self._join_user_path(draft_path, draft_name)
        draft_id = str(uuid.uuid4()).upper()

        content_path = draft_dir / "draft_content.json"
        with open(content_path, encoding="utf-8") as f:  # noqa: PTH123
            content = json.load(f)
        content["id"] = draft_id
        content["name"] = draft_name
        content["create_time"] = now_us
        content["update_time"] = now_us
        with open(content_path, "w", encoding="utf-8") as f:  # noqa: PTH123
            json.dump(content, f, ensure_ascii=False)

        meta_path = draft_dir / "draft_meta_info.json"
        with open(meta_path, encoding="utf-8") as f:  # noqa: PTH123
            meta = json.load(f)
        meta["draft_id"] = draft_id
        meta["draft_name"] = draft_name
        meta["draft_root_path"] = draft_root
        meta["draft_fold_path"] = draft_fold_path
        meta["draft_new_version"] = content.get("new_version", "110.0.0")
        meta["tm_draft_cloud_modified"] = now_us
        meta["tm_duration"] = content.get("duration", 0)
        self._sync_meta_materials(meta, content, now_us)
        with open(meta_path, "w", encoding="utf-8") as f:  # noqa: PTH123
            json.dump(meta, f, ensure_ascii=False)

    def _zip_draft_dirs(self, *, zip_path: Path, draft_dirs: list[tuple[str, Path]]) -> None:
        """将一个或多个草稿目录打包为 ZIP。"""
        video_suffixes = {".mp4", ".webm", ".mov", ".avi", ".mkv"}
        with zipfile.ZipFile(zip_path, "w") as zf:
            for draft_name, draft_dir in draft_dirs:
                for file in draft_dir.rglob("*"):
                    if file.is_file():
                        arcname = f"{draft_name}/{file.relative_to(draft_dir)}"
                        compress = zipfile.ZIP_STORED if file.suffix.lower() in video_suffixes else zipfile.ZIP_DEFLATED
                        zf.write(file, arcname, compress_type=compress)

    def _build_episode_draft_dir(
        self,
        *,
        project_name: str,
        project: dict,
        project_dir: Path,
        episode: int,
        draft_path: str,
        tmp_dir: Path,
        use_draft_info_name: bool,
    ) -> tuple[str, Path]:
        """在 tmp_dir 中生成某一集的剪映草稿目录。"""
        script_data, _ = self._find_episode_script(project_name, project, episode)

        content_mode = script_data.get("content_mode", "narration")
        clips = self._collect_video_clips(script_data, project_dir)
        if not clips:
            raise ValueError(f"第 {episode} 集没有已完成的视频片段，请先生成视频")

        width, height = self._resolve_canvas_size(project, clips[0]["abs_path"])
        raw_title = project.get("title", project_name)
        safe_title = raw_title.replace("/", "_").replace("\\", "_").replace("..", "_")
        draft_name = f"{safe_title}_第{episode}集"

        staging_dir = tmp_dir / f"staging_episode_{episode}"
        staging_dir.mkdir()

        local_clips = []
        for clip in clips:
            src = clip["abs_path"]
            dst = staging_dir / src.name
            try:
                dst.hardlink_to(src)
            except OSError:
                shutil.copy2(src, dst)
            local_clips.append({**clip, "local_path": str(dst)})

        draft_dir = tmp_dir / draft_name
        self._generate_draft(
            draft_dir=draft_dir,
            draft_name=draft_name,
            clips=local_clips,
            width=width,
            height=height,
            content_mode=content_mode,
        )

        assets_dir = draft_dir / "assets"
        assets_dir.mkdir(exist_ok=True)
        for clip in local_clips:
            src = Path(clip["local_path"])
            dst = assets_dir / src.name
            shutil.move(str(src), str(dst))

        draft_content_path = draft_dir / "draft_content.json"
        self._replace_paths_in_draft(
            json_path=draft_content_path,
            tmp_prefix=str(staging_dir),
            target_prefix=self._join_user_path(draft_path, draft_name, "assets"),
        )
        self._finalize_draft_metadata(draft_dir=draft_dir, draft_name=draft_name, draft_path=draft_path)

        if use_draft_info_name:
            shutil.copy2(draft_content_path, draft_dir / "draft_info.json")

        return draft_name, draft_dir

    def _build_combined_draft_dir(
        self,
        *,
        project_name: str,
        project: dict,
        project_dir: Path,
        episodes: list[int],
        draft_path: str,
        tmp_dir: Path,
        use_draft_info_name: bool,
    ) -> tuple[str, Path]:
        """在 tmp_dir 中生成选中剧集合并后的单个剪映草稿目录。"""
        raw_title = project.get("title", project_name)
        draft_name = raw_title.replace("/", "_").replace("\\", "_").replace("..", "_")
        staging_dir = tmp_dir / "staging_combined"
        staging_dir.mkdir()

        local_clips: list[dict[str, Any]] = []
        content_modes: list[str] = []
        first_video_path: Path | None = None
        for episode in episodes:
            script_data, _ = self._find_episode_script(project_name, project, episode)
            content_modes.append(script_data.get("content_mode", "narration"))
            clips = self._collect_video_clips(script_data, project_dir)
            if not clips:
                raise ValueError(f"第 {episode} 集没有已完成的视频片段，请先生成视频")
            if first_video_path is None:
                first_video_path = clips[0]["abs_path"]

            for clip in clips:
                src = clip["abs_path"]
                dst = staging_dir / src.name
                try:
                    dst.hardlink_to(src)
                except OSError:
                    shutil.copy2(src, dst)
                local_clips.append({**clip, "local_path": str(dst)})

        content_mode = "narration" if content_modes and all(mode == "narration" for mode in content_modes) else "drama"
        width, height = self._resolve_canvas_size(project, first_video_path)
        draft_dir = tmp_dir / draft_name
        self._generate_draft(
            draft_dir=draft_dir,
            draft_name=draft_name,
            clips=local_clips,
            width=width,
            height=height,
            content_mode=content_mode,
        )

        assets_dir = draft_dir / "assets"
        assets_dir.mkdir(exist_ok=True)
        for clip in local_clips:
            src = Path(clip["local_path"])
            dst = assets_dir / src.name
            shutil.move(str(src), str(dst))

        draft_content_path = draft_dir / "draft_content.json"
        self._replace_paths_in_draft(
            json_path=draft_content_path,
            tmp_prefix=str(staging_dir),
            target_prefix=self._join_user_path(draft_path, draft_name, "assets"),
        )
        self._finalize_draft_metadata(draft_dir=draft_dir, draft_name=draft_name, draft_path=draft_path)

        if use_draft_info_name:
            shutil.copy2(draft_content_path, draft_dir / "draft_info.json")

        return draft_name, draft_dir

    # ------------------------------------------------------------------
    # 公开方法
    # ------------------------------------------------------------------

    def export_episode_draft(
        self,
        project_name: str,
        episode: int,
        draft_path: str,
        *,
        use_draft_info_name: bool = True,
    ) -> Path:
        """
        导出指定集的剪映草稿 ZIP。

        Returns:
            ZIP 文件路径（临时文件，调用方负责清理）

        Raises:
            FileNotFoundError: 项目或剧本不存在
            ValueError: 无可导出的视频片段
        """
        project = self.pm.load_project(project_name)
        project_dir = self.pm.get_project_path(project_name)
        tmp_dir = Path(tempfile.mkdtemp(prefix="arcreel_jy_"))
        try:
            draft_name, draft_dir = self._build_episode_draft_dir(
                project_name=project_name,
                project=project,
                project_dir=project_dir,
                episode=episode,
                draft_path=draft_path,
                tmp_dir=tmp_dir,
                use_draft_info_name=use_draft_info_name,
            )
            zip_path = tmp_dir / f"{draft_name}.zip"
            self._zip_draft_dirs(zip_path=zip_path, draft_dirs=[(draft_name, draft_dir)])

            return zip_path
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def export_episodes_drafts(
        self,
        project_name: str,
        episodes: list[int],
        draft_path: str,
        *,
        combine: bool = True,
        use_draft_info_name: bool = True,
    ) -> Path:
        """
        批量导出多集剪映草稿 ZIP。

        Returns:
            ZIP 文件路径（临时文件，调用方负责清理）
        """
        if not episodes:
            raise ValueError("请选择至少一集")

        unique_episodes = list(dict.fromkeys(episodes))
        project = self.pm.load_project(project_name)
        project_dir = self.pm.get_project_path(project_name)
        raw_title = project.get("title", project_name)
        safe_title = raw_title.replace("/", "_").replace("\\", "_").replace("..", "_")

        tmp_dir = Path(tempfile.mkdtemp(prefix="arcreel_jy_"))
        try:
            if combine:
                draft_name, draft_dir = self._build_combined_draft_dir(
                    project_name=project_name,
                    project=project,
                    project_dir=project_dir,
                    episodes=unique_episodes,
                    draft_path=draft_path,
                    tmp_dir=tmp_dir,
                    use_draft_info_name=use_draft_info_name,
                )
                draft_dirs = [(draft_name, draft_dir)]
            else:
                draft_dirs = [
                    self._build_episode_draft_dir(
                        project_name=project_name,
                        project=project,
                        project_dir=project_dir,
                        episode=episode,
                        draft_path=draft_path,
                        tmp_dir=tmp_dir,
                        use_draft_info_name=use_draft_info_name,
                    )
                    for episode in unique_episodes
                ]

            zip_path = tmp_dir / f"{safe_title}_剪映草稿_共{len(unique_episodes)}集.zip"
            self._zip_draft_dirs(zip_path=zip_path, draft_dirs=draft_dirs)
            return zip_path
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise
