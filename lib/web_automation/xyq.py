"""小云雀网页自动化封装。

该模块把 ``https://xyq.jianying.com/`` 包成可被 image/video backend 调用的异步 runner。
它不处理登录流程，依赖 Playwright persistent profile 里已有登录态。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import shutil
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

XYQ_PROVIDER_ID = "xyq-web"
XYQ_DEFAULT_PROFILE_DIR = "~/.arcreel-browser-profiles/xyq"
XYQ_DEFAULT_DOWNLOAD_DIR = "~/downbyxyq"
XYQ_DEFAULT_TIMEOUT_SECONDS = 2700
XYQ_MAX_REFERENCE_IMAGES = 7

XYQ_IMAGE_MODEL_SEEDREAM_4_AESTHETIC = "seedream-4.0-aesthetic"
XYQ_VIDEO_MODEL_SEEDANCE_2 = "seedance-2.0"
XYQ_VIDEO_MODEL_SEEDANCE_2_FAST = "seedance-2.0-fast"

_PROFILE_LOCK = asyncio.Lock()
_IMAGE_SINGLE_HINT = "只生成一张图。"
_VIDEO_QUALITY_GUIDE = "电影级高清画质，主体清晰，动作连贯，镜头稳定。"
_VIDEO_NEGATIVE_TAIL = "禁止出现：背景音乐、血迹、文字字幕、水印。"
_LEGACY_VIDEO_NEGATIVE_TAILS = (
    "禁止出现：BGM、文字字幕、水印。",
    "禁止出现：血迹、文字字幕、水印。",
)
_MIN_ACCEPTABLE_IMAGE_LONG_EDGE = 700
_DOWNLOAD_TRIGGER_TIMEOUT_MS = 60_000
_IMAGE_DOWNLOAD_STABILIZE_MS = 5_000
_VIDEO_POLL_INTERVAL_SECONDS = 10 * 60
_VIDEO_SUBMISSION_CONFIRM_TIMEOUT_SECONDS = 120
_VIDEO_SUBMISSION_MATCH_WINDOW_SECONDS = 120
_VIDEO_HISTORY_SETTLE_MS = 1_500
_HOME_URL = "https://xyq.jianying.com/home?from_page=xiaoyunque_landing_page&tab_name=home"
_XYQ_VIDEO_DURATION_STORAGE_KEYS = (
    "__pippitcn_home_videoPartDuration",
    "__pippitcn_home_agentVideoDuration",
)
_XYQ_VIDEO_MODEL_MENU_PATTERNS: dict[str, str | re.Pattern[str]] = {
    XYQ_VIDEO_MODEL_SEEDANCE_2: re.compile(r"^Seedance 2\.0$"),
    XYQ_VIDEO_MODEL_SEEDANCE_2_FAST: re.compile(r"^Seedance 2\.0 Fast$"),
}
_PREVIEW_CONTAINER_SELECTOR = (
    "[role=dialog], "
    ".semi-modal, .arco-modal, .lv-modal, .ReactModal__Content, "
    "[class*='Modal'], [class*='modal'], [class*='preview'], [class*='Preview'], "
    "[class*='viewer'], [class*='Viewer']"
)


@dataclass(frozen=True)
class XyqReference:
    """被上传到小云雀的参考素材。"""

    path: Path
    label: str = ""


@dataclass(frozen=True)
class _PreparedReference:
    source_path: Path
    staged_path: Path
    display_name: str
    label: str


@dataclass(frozen=True)
class _VideoSubmission:
    submitted_at: datetime
    detail_text: str


def _parse_bool(value: str | bool | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_int(value: str | int | None, default: int) -> int:
    if isinstance(value, int):
        return value
    if value is None or value == "":
        return default
    try:
        return int(str(value).strip())
    except ValueError:
        return default


def _expand_path(raw: str | os.PathLike[str] | None, default: str) -> Path:
    value = str(raw or default)
    return Path(value).expanduser()


def _sanitize_stem(raw: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z._-]+", "_", raw).strip("._-")
    return sanitized[:48] or "ref"


def _image_prompt(prompt: str) -> str:
    text = (prompt or "").strip()
    if _IMAGE_SINGLE_HINT not in text:
        text = f"{text}\n{_IMAGE_SINGLE_HINT}" if text else _IMAGE_SINGLE_HINT
    return text


def _video_prompt(prompt: str) -> str:
    text = (prompt or "").replace("@", "").strip()
    for tail in _LEGACY_VIDEO_NEGATIVE_TAILS:
        text = text.replace(tail, "").strip()
    text = text.replace(_VIDEO_NEGATIVE_TAIL, "").strip()
    if _VIDEO_QUALITY_GUIDE not in text:
        text = f"{text.rstrip()}\n\n{_VIDEO_QUALITY_GUIDE}" if text else _VIDEO_QUALITY_GUIDE
    return f"{text.rstrip()}\n\n{_VIDEO_NEGATIVE_TAIL}" if text else _VIDEO_NEGATIVE_TAIL


def _normalize_aspect_ratio(aspect_ratio: str | None) -> Literal["16:9", "9:16", "1:1"]:
    raw = (aspect_ratio or "").strip()
    if raw in {"16:9", "9:16", "1:1"}:
        return raw  # type: ignore[return-value]
    return "16:9" if raw.startswith("16") else "9:16"


def _normalize_duration(duration: int | None) -> int:
    if not duration:
        return 5
    return max(4, min(15, int(duration)))


def _display_name_from_stage(path: Path) -> str:
    return f"{path.name} {path.name}"


def _reference_label(path: Path, idx: int) -> str:
    """生成稳定、唯一的上传文件名前缀，避免多个 full_body.png 在 @ 菜单里重名。"""
    parts = [p for p in path.with_suffix("").parts[-4:] if p not in {os.sep, ""}]
    raw = "_".join(parts) or f"ref_{idx:02d}"
    return _sanitize_stem(raw)


def _prepare_references(
    references: Iterable[XyqReference],
    stage_dir: Path,
    *,
    max_count: int = XYQ_MAX_REFERENCE_IMAGES,
) -> list[_PreparedReference]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[_PreparedReference] = []
    for idx, ref in enumerate(list(references)[:max_count], start=1):
        source = Path(ref.path).expanduser()
        if not source.exists():
            raise FileNotFoundError(f"小云雀参考素材不存在: {source}")
        stem_source = ref.label or _reference_label(source, idx)
        stem = _sanitize_stem(stem_source)
        suffix = source.suffix.lower() or ".png"
        staged = stage_dir / f"{idx:02d}_{stem}{suffix}"
        if staged.exists():
            staged = stage_dir / f"{idx:02d}_{stem}_{source.stat().st_mtime_ns}{suffix}"
        shutil.copyfile(source, staged)
        prepared.append(
            _PreparedReference(
                source_path=source,
                staged_path=staged,
                display_name=_display_name_from_stage(staged),
                label=(ref.label or f"图片{idx}").strip() or f"图片{idx}",
            )
        )
    return prepared


def _read_image_size(path: Path) -> tuple[int, int] | None:
    """读取 PNG/JPEG 尺寸，用于避免把网页缩略图误当成原图保存。"""
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        return width, height
    if data.startswith(b"\xff\xd8"):
        idx = 2
        while idx + 9 < len(data):
            if data[idx] != 0xFF:
                idx += 1
                continue
            marker = data[idx + 1]
            idx += 2
            if marker in {0xD8, 0xD9}:
                continue
            if idx + 2 > len(data):
                return None
            segment_length = int.from_bytes(data[idx : idx + 2], "big")
            if segment_length < 2 or idx + segment_length > len(data):
                return None
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if segment_length >= 7:
                    height = int.from_bytes(data[idx + 3 : idx + 5], "big")
                    width = int.from_bytes(data[idx + 5 : idx + 7], "big")
                    return width, height
                return None
            idx += segment_length
    return None


def _is_low_resolution_image(path: Path) -> bool:
    size = _read_image_size(path)
    if size is None:
        return False
    width, height = size
    return max(width, height) < _MIN_ACCEPTABLE_IMAGE_LONG_EDGE


def _unique_texts(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _format_xyq_detail_time(value: datetime) -> str:
    return f"/{value.month}/{value.day} {value:%H:%M:%S}"


def _format_xyq_history_time_variants(value: datetime) -> list[str]:
    time_part = f"{value:%H:%M:%S}"
    return _unique_texts(
        [
            f"-{value.day} {time_part}",
            f"-{value.day:02d} {time_part}",
            f"{value.day} {time_part}",
            f"{value.day:02d} {time_part}",
            f"/{value.month}/{value.day} {time_part}",
        ]
    )


def _nearby_datetimes(value: datetime, *, window_seconds: int) -> list[datetime]:
    offsets = [0]
    for seconds in range(1, window_seconds + 1):
        offsets.extend([seconds, -seconds])
    return [value + timedelta(seconds=offset) for offset in offsets]


def _parse_xyq_detail_time(text: str, *, fallback_year: int) -> datetime | None:
    match = re.search(r"/?(\d{1,2})/(\d{1,2})\s+(\d{2}:\d{2}:\d{2})", text)
    if not match:
        return None
    month, day, time_part = match.groups()
    try:
        return datetime.strptime(f"{fallback_year}-{month}-{day} {time_part}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _closest_detail_time_text(body_text: str, submitted_at: datetime) -> str | None:
    closest_text: str | None = None
    closest_delta: float | None = None
    for match in re.finditer(r"/(\d{1,2})/(\d{1,2})\s+(\d{2}:\d{2}:\d{2})", body_text):
        month, day, time_part = match.groups()
        try:
            candidate = datetime.strptime(
                f"{submitted_at.year}-{month}-{day} {time_part}",
                "%Y-%m-%d %H:%M:%S",
            )
        except ValueError:
            continue
        delta = abs((candidate - submitted_at).total_seconds())
        if delta > _VIDEO_SUBMISSION_MATCH_WINDOW_SECONDS:
            continue
        if closest_delta is None or delta < closest_delta:
            closest_delta = delta
            closest_text = match.group(0)
    return closest_text


def _video_detail_time_candidates(submitted_at: datetime) -> list[str]:
    return _unique_texts(
        _format_xyq_detail_time(candidate)
        for candidate in _nearby_datetimes(
            submitted_at,
            window_seconds=_VIDEO_SUBMISSION_MATCH_WINDOW_SECONDS,
        )
    )


def _video_history_time_candidates(submission: _VideoSubmission) -> list[str]:
    parsed_detail = _parse_xyq_detail_time(submission.detail_text, fallback_year=submission.submitted_at.year)
    datetimes = []
    if parsed_detail is not None:
        datetimes.append(parsed_detail)
    datetimes.extend(
        _nearby_datetimes(
            submission.submitted_at,
            window_seconds=_VIDEO_SUBMISSION_MATCH_WINDOW_SECONDS,
        )
    )
    return _unique_texts(text for candidate in datetimes for text in _format_xyq_history_time_variants(candidate))


def _closest_history_time_text(body_text: str, submitted_at: datetime) -> str | None:
    closest_text: str | None = None
    closest_delta: float | None = None
    for match in re.finditer(r"-(\d{1,2})\s+(\d{2}:\d{2}:\d{2})", body_text):
        day, time_part = match.groups()
        try:
            candidate = datetime.strptime(
                f"{submitted_at.year}-{submitted_at.month}-{day} {time_part}",
                "%Y-%m-%d %H:%M:%S",
            )
        except ValueError:
            continue
        delta = abs((candidate - submitted_at).total_seconds())
        if delta > _VIDEO_SUBMISSION_MATCH_WINDOW_SECONDS:
            continue
        if closest_delta is None or delta < closest_delta:
            closest_delta = delta
            closest_text = match.group(0)
    return closest_text


class XyqWebRunner:
    """小云雀网页自动化 runner。

    后端任务共享同一个 persistent profile，因此所有生成调用用进程内锁串行化。
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        profile_dir: str | None = None,
        download_dir: str | None = None,
        headless: str | bool | None = None,
        timeout_seconds: str | int | None = None,
    ) -> None:
        self.model = model or XYQ_IMAGE_MODEL_SEEDREAM_4_AESTHETIC
        self.profile_dir = _expand_path(profile_dir, XYQ_DEFAULT_PROFILE_DIR)
        self.download_dir = _expand_path(download_dir, XYQ_DEFAULT_DOWNLOAD_DIR)
        self.headless = _parse_bool(headless, default=False)
        self.timeout_seconds = _parse_int(timeout_seconds, XYQ_DEFAULT_TIMEOUT_SECONDS)

    async def generate_image(
        self,
        *,
        prompt: str,
        output_path: Path,
        references: list[XyqReference] | None = None,
        aspect_ratio: str = "16:9",
    ) -> Path:
        async with _PROFILE_LOCK:
            return await self._generate_image_locked(
                prompt=prompt,
                output_path=output_path,
                references=references or [],
                aspect_ratio=aspect_ratio,
            )

    async def generate_video(
        self,
        *,
        prompt: str,
        output_path: Path,
        references: list[XyqReference] | None = None,
        start_image: Path | None = None,
        end_image: Path | None = None,
        aspect_ratio: str = "9:16",
        duration_seconds: int = 5,
    ) -> Path:
        async with _PROFILE_LOCK:
            submission = await self._submit_video_task_locked(
                prompt=prompt,
                references=references or [],
                start_image=start_image,
                end_image=end_image,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
            )
        await self._poll_video_download(submission, output_path)
        return output_path

    async def _generate_image_locked(
        self,
        *,
        prompt: str,
        output_path: Path,
        references: list[XyqReference],
        aspect_ratio: str,
    ) -> Path:
        async with _playwright_context(self) as page:
            logger.info("小云雀图片生成：进入首页")
            await self._goto_home(page)
            logger.info("小云雀图片生成：打开生成图片")
            await page.get_by_role("button", name="生成图片").click(timeout=20_000)
            logger.info("小云雀图片生成：选择模型")
            await self._select_image_model(page)
            logger.info("小云雀图片生成：选择比例 %s", aspect_ratio)
            await self._select_aspect_ratio(page, aspect_ratio)
            initial_image_count = await self._count_result_images(page)

            with tempfile.TemporaryDirectory(prefix="arcreel-xyq-img-") as tmp_dir:
                prepared = _prepare_references(references, Path(tmp_dir))
                if prepared:
                    logger.info("小云雀图片生成：上传 %d 张参考图", len(prepared))
                    await self._upload_references(page, prepared)
                    await self._fill_prompt(page, _image_prompt(prompt))
                else:
                    logger.info("小云雀图片生成：填写文生图提示词")
                    await self._fill_prompt(page, _image_prompt(prompt))

                logger.info("小云雀图片生成：点击生成")
                await self._click_create(page)
                logger.info("小云雀图片生成：等待下载")
                await self._download_result(
                    page,
                    output_path,
                    media_kind="image",
                    initial_image_count=initial_image_count,
                )
        return output_path

    async def _submit_video_task_locked(
        self,
        *,
        prompt: str,
        references: list[XyqReference],
        start_image: Path | None,
        end_image: Path | None,
        aspect_ratio: str,
        duration_seconds: int,
    ) -> _VideoSubmission:
        async with _playwright_context(self) as page:
            await self._goto_home(page)
            await self._open_video_workspace(
                page,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
            )
            prompt_text = _video_prompt(prompt)

            with tempfile.TemporaryDirectory(prefix="arcreel-xyq-video-") as tmp_dir:
                video_refs = list(references)
                if not video_refs and start_image is not None:
                    video_refs.append(XyqReference(path=start_image, label="start_frame"))
                if end_image is not None:
                    video_refs.append(XyqReference(path=end_image, label="end_frame"))

                prepared = _prepare_references(video_refs, Path(tmp_dir))
                if prepared:
                    mode = "首尾帧" if start_image is not None and end_image is not None else "全能参考"
                    await self._select_video_reference_mode(page, mode)
                    await self._upload_references(page, prepared)
                    await self._fill_prompt_with_refs(page, prompt_text, prepared)
                else:
                    await self._fill_prompt(page, prompt_text)

                submitted_at = datetime.now()
                await self._click_create(page)
                detail_text = await self._capture_video_submission_detail_time(page, submitted_at)
                logger.info("小云雀视频生成已提交，提交时间: %s", detail_text)
                return _VideoSubmission(submitted_at=submitted_at, detail_text=detail_text)

    async def _capture_video_submission_detail_time(self, page, submitted_at: datetime) -> str:
        deadline = time.monotonic() + _VIDEO_SUBMISSION_CONFIRM_TIMEOUT_SECONDS
        confirmed_thread = False
        while time.monotonic() < deadline:
            if "thread_id=" in page.url:
                confirmed_thread = True
            try:
                body_text = await page.locator("body").inner_text(timeout=2_000)
            except Exception:
                body_text = ""
            matched = _closest_detail_time_text(body_text, submitted_at)
            if matched:
                return matched
            await page.wait_for_timeout(1_000)

        if confirmed_thread:
            fallback = _format_xyq_detail_time(submitted_at)
            logger.warning("小云雀已进入任务详情页但未识别提交时间，使用本地时间兜底: %s", fallback)
            return fallback

        raise RuntimeError(
            "小云雀视频任务未确认提交成功：提交后未进入任务详情页，也未出现任务提交时间；"
            "已停止后续下载轮询，请检查页面是否有错误提示或重新提交。"
        )

    async def _poll_video_download(self, submission: _VideoSubmission, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self.timeout_seconds
        attempt = 0

        while True:
            attempt += 1
            async with _PROFILE_LOCK:
                async with _playwright_context(self) as page:
                    logger.info("小云雀视频下载轮询第 %d 次，提交时间: %s", attempt, submission.detail_text)
                    if await self._try_download_video_from_history(page, submission, output_path):
                        return

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"小云雀视频生成超时：提交时间 {submission.detail_text}，"
                    f"已等待 {self.timeout_seconds} 秒仍未出现下载按钮"
                )
            wait_seconds = min(_VIDEO_POLL_INTERVAL_SECONDS, max(1, int(remaining)))
            logger.info("小云雀视频尚未生成，%d 秒后再次检查: %s", wait_seconds, submission.detail_text)
            await asyncio.sleep(wait_seconds)

    async def _try_download_video_from_history(self, page, submission: _VideoSubmission, output_path: Path) -> bool:
        await self._goto_home(page)
        await self._open_history_all_tab(page)
        thread_page = await self._open_video_thread_from_history(page, submission)
        if thread_page is None:
            logger.info("小云雀历史列表尚未找到视频任务: %s", submission.detail_text)
            return False
        try:
            return await self._try_download_video_from_thread(thread_page, output_path)
        finally:
            try:
                await thread_page.close()
            except Exception:
                logger.info("小云雀关闭视频任务弹窗失败，继续后续轮询")

    async def _open_history_all_tab(self, page) -> None:
        try:
            await page.get_by_text("全部").click(timeout=15_000)
        except Exception:
            logger.info("小云雀历史页未找到“全部”入口，继续在当前列表查找任务")
        await page.wait_for_timeout(_VIDEO_HISTORY_SETTLE_MS)

    async def _open_video_thread_from_history(self, page, submission: _VideoSubmission):
        try:
            body_text = await page.locator("body").inner_text(timeout=3_000)
        except Exception:
            body_text = ""

        direct_candidates = [text for text in _video_history_time_candidates(submission) if text in body_text]
        for text in direct_candidates:
            try:
                async with page.expect_popup(timeout=8_000) as popup_info:
                    await page.get_by_text(text).first.click(timeout=5_000)
                thread_page = await popup_info.value
                await thread_page.wait_for_load_state("domcontentloaded", timeout=20_000)
                return thread_page
            except Exception:
                continue

        closest = _closest_history_time_text(body_text, submission.submitted_at)
        if not closest:
            return None
        try:
            async with page.expect_popup(timeout=8_000) as popup_info:
                await page.get_by_text(closest).first.click(timeout=5_000)
            thread_page = await popup_info.value
            await thread_page.wait_for_load_state("domcontentloaded", timeout=20_000)
            return thread_page
        except Exception:
            logger.info("小云雀按最近历史时间打开任务失败: %s", closest)
            return None

    async def _try_download_video_from_thread(self, page, output_path: Path) -> bool:
        try:
            await page.get_by_role("button", name="下载").first.wait_for(timeout=10_000)
        except Exception:
            logger.info("小云雀视频任务页暂未出现下载按钮")
            return False

        try:
            await self._download_by_button(
                page,
                output_path,
                timeout_ms=min(self.timeout_seconds * 1000, _DOWNLOAD_TRIGGER_TIMEOUT_MS),
                button_index=-1,
            )
            logger.info("小云雀视频下载完成: %s", output_path)
            return True
        except Exception as exc:
            logger.info("小云雀视频下载按钮未触发下载: %s", exc)
            return False

    async def _goto_home(self, page) -> None:
        await page.goto(_HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        await self._wait_home_ready(page)

    async def _wait_home_ready(self, page) -> None:
        try:
            await page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception:
            logger.info("小云雀页面 networkidle 等待超时，继续检查创作按钮")
        try:
            await page.get_by_role("button", name=re.compile("生成图片|沉浸式短片")).first.wait_for(timeout=30_000)
        except Exception as exc:
            raise RuntimeError("小云雀未进入创作首页，可能是登录态失效。请用同一 profile 手动登录后重试。") from exc

    async def _reload_home(self, page) -> None:
        try:
            await page.reload(wait_until="domcontentloaded", timeout=60_000)
            await self._wait_home_ready(page)
        except Exception:
            await self._goto_home(page)

    async def _open_video_workspace(self, page, *, aspect_ratio: str, duration_seconds: int) -> None:
        duration = _normalize_duration(duration_seconds)
        last_seen: int | None = None
        for attempt in range(2):
            await self._store_video_duration_preference(page, duration)
            await self._reload_home(page)
            await page.get_by_role("button", name="沉浸式短片").click(timeout=20_000)
            await self._select_video_model(page)
            await self._select_aspect_ratio(page, aspect_ratio)
            last_seen = await self._read_visible_video_duration(page)
            if last_seen != duration:
                await self._set_visible_video_duration(page, duration)
                last_seen = await self._read_visible_video_duration(page)
            if last_seen == duration:
                return
            logger.warning(
                "小云雀视频时长校验失败，第 %d 次尝试期望 %s 秒，页面当前 %s 秒",
                attempt + 1,
                duration,
                last_seen,
            )
        current = f"{last_seen} 秒" if last_seen is not None else "未知"
        raise RuntimeError(f"小云雀未能设置视频时长 {duration} 秒：页面当前时长 {current}")

    async def _store_video_duration_preference(self, page, duration: int) -> None:
        await page.evaluate(
            """([keys, value]) => {
                for (const key of keys) {
                    window.localStorage.setItem(key, value);
                }
            }""",
            [list(_XYQ_VIDEO_DURATION_STORAGE_KEYS), str(duration)],
        )

    async def _read_visible_video_duration(self, page) -> int | None:
        pattern = re.compile(r"^\s*(\d+)\s*秒\s*$")
        locators = (
            page.locator("button.videoPartDurationTrigger-KWTics"),
            page.get_by_role("button", name=pattern),
            page.locator("button").filter(has_text=pattern),
        )
        for locator in locators:
            try:
                count = min(await locator.count(), 10)
            except Exception:
                continue
            for index in range(count):
                try:
                    text = await locator.nth(index).inner_text(timeout=1_000)
                except Exception:
                    continue
                match = pattern.match(text)
                if match:
                    return int(match.group(1))
        return None

    async def _set_visible_video_duration(self, page, duration: int) -> None:
        opened = await self._click_toolbar_button(page, text_pattern=r"^\d+秒$")
        if not opened:
            logger.info("小云雀新版视频时长入口未找到，跳过数字输入兜底")
            return

        inputs = (
            page.locator("input.videoPartDurationNumberInput-BUXHCL"),
            page.locator("input[type=number][min][max]"),
        )
        for locator in inputs:
            try:
                target = locator.last
                await target.wait_for(timeout=5_000)
                await target.fill(str(duration), timeout=5_000)
                await target.press("Enter", timeout=2_000)
                await page.wait_for_timeout(500)
                return
            except Exception:
                continue
        logger.info("小云雀已打开视频时长入口，但未找到数字输入框")

    async def _select_image_model(self, page) -> None:
        if self.model != XYQ_IMAGE_MODEL_SEEDREAM_4_AESTHETIC:
            logger.info("小云雀图片 model=%s 暂按 Seedream 4.0 美感版选择", self.model)
        await self._open_model_dropdown(page, family_pattern="Seedream")
        await self._click_model_option(page, "Seedream 4.0 美感版")

    async def _select_video_model(self, page) -> None:
        pattern = _XYQ_VIDEO_MODEL_MENU_PATTERNS.get(self.model)
        if pattern is None:
            logger.warning("小云雀视频 model=%s 暂不支持页面选择，回退到 Seedance 2.0 Fast", self.model)
            pattern = _XYQ_VIDEO_MODEL_MENU_PATTERNS[XYQ_VIDEO_MODEL_SEEDANCE_2_FAST]
        await self._open_model_dropdown(page, family_pattern="Seedance")
        await self._click_model_option(page, pattern)

    async def _click_model_option(self, page, pattern: str | re.Pattern[str]) -> None:
        candidates = [
            page.locator("[role=option], [role=menuitem], button, div").filter(has_text=pattern).last,
            page.get_by_text(pattern).last,
            page.locator("div").filter(has_text=pattern).last,
        ]
        errors: list[str] = []
        for locator in candidates:
            try:
                await locator.click(timeout=8_000)
                return
            except Exception as exc:
                errors.append(str(exc).splitlines()[0])
        raise RuntimeError(f"小云雀未能选择模型 {pattern!r}: {'; '.join(errors[-3:])}")

    async def _open_model_dropdown(self, page, *, family_pattern: str = "Seedream|Seedance") -> None:
        if await self._click_toolbar_button(page, text_pattern=family_pattern):
            return
        try:
            await page.locator(".lucide.lucide-chevron-down").first.click(timeout=8_000)
        except Exception:
            await page.get_by_text(re.compile(family_pattern)).first.click(timeout=8_000)

    async def _select_aspect_ratio(self, page, aspect_ratio: str) -> None:
        ratio = _normalize_aspect_ratio(aspect_ratio)
        candidates = {
            "16:9": ["16:9（横屏）", ":9（横屏）"],
            "9:16": ["9:16（竖屏）", ":16（竖屏）"],
            "1:1": ["1:1", "方屏"],
        }[ratio]

        if not await self._click_toolbar_button(page, exact_text="比例"):
            try:
                await page.locator(".trigger-Mt5lwU").first.click(timeout=8_000)
            except Exception:
                await page.get_by_role("menuitem", name=re.compile("9|16|1:1")).first.click(timeout=8_000)

        for text in candidates:
            try:
                await page.get_by_role("menuitem", name=text, exact=True).click(timeout=5_000)
                return
            except Exception:
                pass
            try:
                await page.locator("div").filter(has_text=text).last.click(timeout=5_000)
                return
            except Exception:
                continue
        logger.warning("小云雀未能切换比例到 %s，继续使用页面当前比例", ratio)

    async def _select_video_reference_mode(self, page, mode: Literal["全能参考", "首尾帧"]) -> None:
        names = ("全能参考", "首尾帧")
        opened = False
        for name in names:
            if await self._click_toolbar_button(page, exact_text=name):
                opened = True
                break
            try:
                await page.get_by_role("button", name=name, exact=True).click(timeout=5_000)
                opened = True
                break
            except Exception:
                continue
        if not opened:
            logger.warning("小云雀未找到参考模式切换按钮，继续使用页面当前模式")
            return
        try:
            if mode == "全能参考":
                await page.locator("div").filter(has_text=re.compile(r"^全能参考$")).last.click(timeout=8_000)
            else:
                await page.locator("div").filter(has_text=re.compile(r"^首尾帧$")).last.click(timeout=8_000)
        except Exception:
            logger.warning("小云雀未能切换参考模式到 %s，继续使用页面当前模式", mode)

    async def _click_toolbar_button(
        self,
        page,
        *,
        exact_text: str | None = None,
        text_pattern: str | None = None,
        title: str | None = None,
        aria_label: str | None = None,
    ) -> bool:
        try:
            return bool(
                await page.evaluate(
                    """({exactText, textPattern, title, ariaLabel}) => {
                        const re = textPattern ? new RegExp(textPattern) : null;
                        const buttons = Array.from(document.querySelectorAll("button"));
                        const button = buttons.find((el) => {
                            const rect = el.getBoundingClientRect();
                            if (rect.width <= 0 || rect.height <= 0) return false;
                            const style = window.getComputedStyle(el);
                            if (style.display === "none" || style.visibility === "hidden") return false;
                            const cls = String(el.className || "");
                            const isToolbar = (
                                cls.includes("operationItem-") ||
                                cls.includes("uploadConfigButton-") ||
                                cls.includes("configScrollArrow-")
                            );
                            if (!isToolbar) return false;
                            const text = (el.innerText || el.textContent || "").replace(/\\s+/g, " ").trim();
                            const elTitle = el.getAttribute("title") || "";
                            const elAria = el.getAttribute("aria-label") || "";
                            if (exactText && text !== exactText) return false;
                            if (re && !re.test(text)) return false;
                            if (title && elTitle !== title) return false;
                            if (ariaLabel && elAria !== ariaLabel) return false;
                            return true;
                        });
                        if (!button) return false;
                        button.click();
                        return true;
                    }""",
                    {
                        "exactText": exact_text,
                        "textPattern": text_pattern,
                        "title": title,
                        "ariaLabel": aria_label,
                    },
                )
            )
        except Exception:
            return False

    async def _upload_references(self, page, references: list[_PreparedReference]) -> None:
        if not references:
            return
        for ref in references:
            await self._open_reference_upload_menu(page)
            await self._upload_one_reference(page, ref)
            await self._wait_reference_uploaded(page, ref)
            await page.wait_for_timeout(800)
        await self._close_upload_panel(page)

    async def _open_reference_upload_menu(self, page) -> None:
        try:
            if await page.get_by_role("button", name=re.compile("本地上传")).first.is_visible(timeout=500):
                return
        except Exception:
            pass
        if not await self._click_toolbar_button(page, title="上传参考素材"):
            await page.get_by_role("button", name="上传参考素材").click(timeout=20_000)
        try:
            await page.get_by_role("button", name=re.compile("本地上传")).first.wait_for(timeout=8_000)
        except Exception as exc:
            raise RuntimeError("小云雀未能打开上传参考素材菜单") from exc

    async def _upload_one_reference(self, page, ref: _PreparedReference) -> None:
        # 小云雀页面里同时存在“导入预设”等上传入口。必须避开预设入口，
        # 否则图片会被当成预设文件导入，页面报“导入预设失败，请检查文件格式”。
        local_uploads = await self._rank_local_upload_buttons(page)
        for _, index, context_levels in local_uploads:
            context = " | ".join(context_levels)
            if self._looks_like_preset_context(context_levels):
                logger.info("小云雀跳过疑似导入预设的本地上传按钮: %s", context[:120])
                continue
            local_upload = page.get_by_role("button", name=re.compile("本地上传")).nth(index)
            try:
                async with page.expect_file_chooser(timeout=12_000) as chooser_info:
                    await local_upload.click(timeout=12_000)
                file_chooser = await chooser_info.value
                accept = (await file_chooser.element.get_attribute("accept")) or ""
                is_reference_context = self._looks_like_reference_upload_context(context_levels)
                if accept and not self._accepts_image_file(accept) and not is_reference_context:
                    logger.info("小云雀跳过非图片 file chooser: accept=%s context=%s", accept, context[:120])
                    continue
                if not accept and not is_reference_context:
                    logger.info("小云雀跳过未声明图片格式的本地上传入口: context=%s", context[:120])
                    continue
                await file_chooser.set_files(str(ref.staged_path), timeout=20_000)
                return
            except Exception as exc:
                logger.info(
                    "小云雀未能通过本地上传按钮上传 %s: index=%s error=%s",
                    ref.staged_path.name,
                    index,
                    exc,
                )

        inputs = page.locator("input[type=file]")
        count = await inputs.count()
        for index in range(count - 1, -1, -1):
            candidate = inputs.nth(index)
            accept = (await candidate.get_attribute("accept", timeout=1_000)) or ""
            if accept and not self._accepts_image_file(accept):
                continue
            if not accept:
                continue
            context_levels = await self._nearby_text_levels(candidate)
            context = " | ".join(context_levels)
            if self._looks_like_preset_context(context_levels):
                logger.info("小云雀跳过疑似导入预设的 file input: accept=%s context=%s", accept, context[:120])
                continue
            try:
                await candidate.set_input_files(str(ref.staged_path), timeout=5_000)
                return
            except Exception:
                continue
        raise RuntimeError(f"小云雀未找到可用的图片上传入口: {ref.staged_path.name}")

    async def _rank_local_upload_buttons(self, page) -> list[tuple[int, int, list[str]]]:
        buttons = page.get_by_role("button", name=re.compile("本地上传"))
        count = await buttons.count()
        ranked: list[tuple[int, int, list[str]]] = []
        for index in range(count):
            button = buttons.nth(index)
            try:
                if not await button.is_visible(timeout=1_000):
                    continue
            except Exception:
                continue
            context_levels = await self._nearby_text_levels(button)
            context = " | ".join(context_levels)
            score = 0
            if re.search(r"参考|素材|图片|上传", context):
                score += 10
            if self._looks_like_preset_context(context_levels):
                score -= 100
            ranked.append((score, index, context_levels))
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return ranked

    async def _nearby_text_levels(self, locator) -> list[str]:
        try:
            levels = await locator.evaluate(
                """el => {
                    const parts = [];
                    let node = el;
                    for (let depth = 0; depth < 4 && node; depth += 1, node = node.parentElement) {
                        const raw = node.innerText || node.textContent || "";
                        const text = raw.replace(/\\s+/g, " ").trim();
                        if (text) parts.push(text.slice(0, 260));
                    }
                    return parts;
                }"""
            )
        except Exception:
            return []
        if not isinstance(levels, list):
            return []
        return [str(item or "") for item in levels if str(item or "").strip()]

    def _looks_like_preset_context(self, levels: list[str]) -> bool:
        # 只看离按钮/input 最近的几层，避免整个弹窗同时包含“上传参考素材”和“导入预设”
        # 时把正确的素材上传入口误判为预设入口。
        nearest = " | ".join(levels[:2])
        return bool(re.search(r"导入预设|预设文件|导入.*预设", nearest or ""))

    def _looks_like_reference_upload_context(self, levels: list[str]) -> bool:
        text = " | ".join(levels)
        return bool(re.search(r"参考|素材|图片|上传参考|角色与素材|本地上传|资产库", text or ""))

    def _accepts_image_file(self, accept: str) -> bool:
        return bool(re.search(r"image|png|jpe?g|webp", accept or "", re.I))

    async def _wait_reference_uploaded(self, page, ref: _PreparedReference) -> None:
        candidates = [
            page.get_by_role("button", name=ref.display_name),
            page.get_by_role("button", name=re.compile(re.escape(ref.staged_path.name))),
            page.get_by_text(ref.staged_path.name, exact=False),
        ]
        for locator in candidates:
            try:
                await locator.last.wait_for(timeout=20_000)
                return
            except Exception:
                continue
        logger.warning("小云雀上传素材后未确认出现在素材列表，继续后续生成: %s", ref.staged_path.name)

    async def _close_upload_panel(self, page) -> None:
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
        except Exception:
            pass

    async def _fill_prompt(self, page, prompt: str) -> None:
        editor = page.locator(".tiptap")
        await editor.click(timeout=20_000)
        await editor.fill((prompt or "").strip(), timeout=20_000)

    async def _fill_prompt_with_refs(self, page, prompt: str, references: list[_PreparedReference]) -> None:
        text = (prompt or "").strip()
        editor = page.locator(".tiptap")
        await editor.click(timeout=20_000)
        await editor.fill("", timeout=20_000)
        for idx, ref in enumerate(references, start=1):
            await self._open_reference_mention_menu(page)
            await self._select_uploaded_reference(page, ref, ordinal=idx)
            punctuation = "。" if idx == len(references) else "，"
            await page.keyboard.insert_text(f"是{ref.label}{punctuation}")
        if text:
            await page.keyboard.insert_text(f"\n\n{text}")

    async def _open_reference_mention_menu(self, page) -> None:
        await page.locator(".tiptap").click(timeout=20_000)
        await page.keyboard.press("End")
        try:
            await page.get_by_role("button", name="@引用角色与素材").click(timeout=5_000)
            await page.get_by_role("button", name=re.compile(r"\.(png|jpg|jpeg|webp)", re.I)).first.wait_for(
                timeout=8_000
            )
            return
        except Exception:
            pass

        await page.keyboard.insert_text("@")
        try:
            await page.get_by_role("button", name=re.compile(r"\.(png|jpg|jpeg|webp)", re.I)).first.wait_for(
                timeout=5_000
            )
            return
        except Exception:
            pass

        try:
            await page.get_by_role("button", name="@引用角色与素材").click(timeout=5_000)
            await page.get_by_role("button", name=re.compile(r"\.(png|jpg|jpeg|webp)", re.I)).first.wait_for(
                timeout=8_000
            )
        except Exception as exc:
            raise RuntimeError("小云雀未能打开 @ 引用素材菜单") from exc

    async def _select_uploaded_reference(self, page, ref: _PreparedReference, *, ordinal: int) -> None:
        escaped_name = re.escape(ref.staged_path.name)
        candidates = [
            page.get_by_role("button", name=ref.display_name),
            page.get_by_role("button", name=re.compile(escaped_name)),
            page.locator("button").filter(has_text=re.compile(escaped_name)),
        ]
        for locator in candidates:
            try:
                await locator.last.click(timeout=8_000)
                return
            except Exception:
                continue
        available = await self._collect_reference_candidate_labels(page)
        raise RuntimeError(
            f"小云雀 @ 菜单未找到上传素材: {ref.staged_path.name}; ordinal={ordinal}; available={available[:20]}"
        )

    async def _collect_reference_candidate_labels(self, page) -> list[str]:
        labels: list[str] = []
        buttons = page.get_by_role("button", name=re.compile(r"\.(png|jpg|jpeg|webp)", re.I))
        try:
            count = min(await buttons.count(), 30)
        except Exception:
            return labels
        for idx in range(count):
            try:
                label = await buttons.nth(idx).inner_text(timeout=1_000)
            except Exception:
                try:
                    label = await buttons.nth(idx).get_attribute("aria-label", timeout=1_000) or ""
                except Exception:
                    label = ""
            label = " ".join(label.split())
            if label:
                labels.append(label)
        return labels

    async def _click_create(self, page) -> None:
        try:
            await page.locator(
                ".lv-btn.lv-btn-secondary.lv-btn-size-default.lv-btn-shape-square.createButton-z2MuSL"
            ).click(timeout=20_000)
        except Exception:
            await page.get_by_role("button", name=re.compile("生成|开始")).last.click(timeout=20_000)

    async def _count_result_images(self, page) -> int:
        try:
            return await page.get_by_role("img", name="image").count()
        except Exception:
            return 0

    async def _wait_new_image_result(self, page, initial_image_count: int | None, timeout_ms: int) -> None:
        if initial_image_count is None:
            await page.get_by_role("img", name="image").last.wait_for(timeout=timeout_ms)
            return
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            try:
                current_count = await page.get_by_role("img", name="image").count()
                if current_count > initial_image_count:
                    return
            except Exception:
                pass
            await page.wait_for_timeout(1000)
        raise TimeoutError("小云雀图片生成超时：未发现新的图片结果")

    async def _download_result(
        self,
        page,
        output_path: Path,
        *,
        media_kind: Literal["image", "video"],
        initial_image_count: int | None = None,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        timeout_ms = self.timeout_seconds * 1000
        if media_kind == "image":
            await self._wait_new_image_result(page, initial_image_count, timeout_ms)
            await self._open_image_preview(page, initial_image_count)
        if media_kind == "image":
            await self._download_image_result(page, output_path, timeout_ms)
            return
        await self._download_by_button(page, output_path, timeout_ms=timeout_ms, button_index=-1)

    async def _open_image_preview(self, page, initial_image_count: int | None) -> None:
        images = page.get_by_role("img", name="image")
        try:
            current_count = await images.count()
        except Exception:
            current_count = 0

        candidate_indexes: list[int] = []
        if initial_image_count is not None and current_count > initial_image_count:
            candidate_indexes.append(initial_image_count)
        if current_count > 0:
            candidate_indexes.extend([current_count - 1, 0])

        seen: set[int] = set()
        for index in candidate_indexes:
            if index < 0 or index in seen:
                continue
            seen.add(index)
            try:
                await images.nth(index).click(timeout=20_000)
                await page.get_by_role("button", name="下载").first.wait_for(timeout=5_000)
                if await self._wait_large_preview_image(page, timeout_ms=15_000):
                    return
                logger.warning("小云雀点击 image[%s] 后未等到高清预览图，尝试其他图片入口", index)
                await self._close_preview_if_possible(page)
                await page.wait_for_timeout(500)
                images = page.get_by_role("img", name="image")
            except Exception:
                continue

        try:
            await images.first.click(timeout=20_000)
            await page.get_by_role("button", name="下载").first.wait_for(timeout=10_000)
            if not await self._wait_large_preview_image(page, timeout_ms=20_000):
                stats = await self._collect_visible_image_stats(page)
                raise RuntimeError(f"未等到高清预览图；visible_images={stats[:8]}")
        except Exception as exc:
            raise RuntimeError("小云雀已生成图片，但未能打开包含下载按钮的图片预览。") from exc

    async def _close_preview_if_possible(self, page) -> None:
        try:
            await page.keyboard.press("Escape")
        except Exception:
            return

    async def _download_by_button(self, page, output_path: Path, *, timeout_ms: int, button_index: int) -> None:
        trigger_timeout = min(timeout_ms, _DOWNLOAD_TRIGGER_TIMEOUT_MS)
        async with page.expect_download(timeout=trigger_timeout) as download_info:
            download_button = page.get_by_role("button", name="下载")
            if button_index < 0:
                await download_button.last.click(timeout=trigger_timeout)
            else:
                await download_button.nth(button_index).click(timeout=trigger_timeout)
        download = await download_info.value
        await download.save_as(str(output_path))

    async def _download_image_result(self, page, output_path: Path, timeout_ms: int) -> None:
        last_size: tuple[int, int] | None = None
        attempts = 0
        tried_buttons: set[tuple[int, int, int, int]] = set()

        try:
            await page.get_by_role("button", name="下载").first.wait_for(timeout=20_000)
            # 小云雀会先插入图片节点和下载按钮，再继续加载预览/高清资源。
            # 这里固定等一下，再确认页面内有高清预览图，避免下载缩略图入口。
            await page.wait_for_timeout(_IMAGE_DOWNLOAD_STABILIZE_MS)
        except Exception:
            logger.warning("小云雀图片预览中未等到全局下载按钮，继续尝试其他兜底路径")

        if not await self._wait_large_preview_image(page, timeout_ms=20_000):
            stats = await self._collect_visible_image_stats(page)
            raise RuntimeError(f"小云雀未等到高清预览图，拒绝点击下载按钮。visible_images={stats[:8]}")

        if await self._save_largest_preview_image(page, output_path):
            last_size = _read_image_size(output_path)
            if not _is_low_resolution_image(output_path):
                return
            output_path.unlink(missing_ok=True)
            logger.warning("小云雀预览大图直接保存仍是低清图片 %s，继续尝试下载按钮", last_size)

        global_buttons = await self._filter_untried_download_buttons(
            await self._collect_global_download_buttons(page),
            tried_buttons,
        )
        for label, button in global_buttons:
            attempts += 1
            if not await self._try_download_locator(page, button, output_path, timeout_ms=timeout_ms, label=label):
                continue
            last_size = _read_image_size(output_path)
            if not _is_low_resolution_image(output_path):
                return
            output_path.unlink(missing_ok=True)
            logger.warning("小云雀通过 %s 下载到低清图片 %s，改用无点击兜底路径", label, last_size)
            break

        preview_buttons = await self._filter_untried_download_buttons(
            await self._collect_download_buttons(page, include_body=False),
            tried_buttons,
        )
        for label, button in preview_buttons:
            attempts += 1
            if not await self._try_download_locator(page, button, output_path, timeout_ms=timeout_ms, label=label):
                continue
            last_size = _read_image_size(output_path)
            if not _is_low_resolution_image(output_path):
                return
            output_path.unlink(missing_ok=True)
            logger.warning("小云雀通过 %s 下载到低清图片 %s，继续尝试", label, last_size)

        body_buttons = await self._filter_untried_download_buttons(
            await self._collect_download_buttons(page, include_body=True),
            tried_buttons,
        )
        for label, button in body_buttons:
            attempts += 1
            if attempts > 8:
                break
            if not await self._try_download_locator(page, button, output_path, timeout_ms=timeout_ms, label=label):
                continue
            last_size = _read_image_size(output_path)
            if not _is_low_resolution_image(output_path):
                return
            output_path.unlink(missing_ok=True)
            logger.warning("小云雀通过 %s 下载到低清图片 %s，继续尝试", label, last_size)

        raise RuntimeError(f"小云雀下载结果疑似缩略图，已拒绝保存。最后尺寸: {last_size}; 尝试按钮数: {attempts}")

    async def _filter_untried_download_buttons(
        self,
        candidates: list[tuple[str, object]],
        tried: set[tuple[int, int, int, int]],
    ) -> list[tuple[str, object]]:
        filtered: list[tuple[str, object]] = []
        for label, button in candidates:
            key = await self._download_button_key(button)
            if key is not None:
                if key in tried:
                    continue
                tried.add(key)
            filtered.append((label, button))
        return filtered

    async def _download_button_key(self, button) -> tuple[int, int, int, int] | None:
        try:
            box = await button.bounding_box(timeout=1_000)
        except Exception:
            return None
        if not box:
            return None
        return (
            round(box["x"]),
            round(box["y"]),
            round(box["width"]),
            round(box["height"]),
        )

    async def _wait_large_preview_image(self, page, *, timeout_ms: int) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            stats = await self._collect_visible_image_stats(page)
            for item in stats:
                if int(item.get("long_edge") or 0) >= _MIN_ACCEPTABLE_IMAGE_LONG_EDGE:
                    return True
            await page.wait_for_timeout(800)
        return False

    async def _collect_visible_image_stats(self, page) -> list[dict[str, object]]:
        try:
            result = await page.evaluate(
                """() => {
                    const isVisible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return (
                            rect.width >= 80 &&
                            rect.height >= 80 &&
                            rect.bottom > 0 &&
                            rect.right > 0 &&
                            rect.top < window.innerHeight &&
                            rect.left < window.innerWidth &&
                            style.display !== "none" &&
                            style.visibility !== "hidden" &&
                            Number(style.opacity || "1") > 0.01
                        );
                    };
                    return Array.from(document.images)
                        .filter((img) => isVisible(img) && (img.naturalWidth || 0) > 0 && (img.naturalHeight || 0) > 0)
                        .map((img) => {
                            const rect = img.getBoundingClientRect();
                            const src = img.currentSrc || img.src || "";
                            return {
                                natural: `${img.naturalWidth}x${img.naturalHeight}`,
                                rendered: `${Math.round(rect.width)}x${Math.round(rect.height)}`,
                                long_edge: Math.max(img.naturalWidth || 0, img.naturalHeight || 0),
                                src_hint: src.slice(0, 96),
                            };
                        })
                        .sort((a, b) => b.long_edge - a.long_edge);
                }"""
            )
        except Exception:
            return []
        return result if isinstance(result, list) else []

    async def _collect_global_download_buttons(self, page) -> list[tuple[str, object]]:
        buttons = page.get_by_role("button", name="下载")
        try:
            count = await buttons.count()
        except Exception:
            return []

        candidates: list[tuple[str, object]] = []
        for index in range(count):
            button = buttons.nth(index)
            try:
                if not await button.is_visible(timeout=1_000):
                    continue
            except Exception:
                continue
            candidates.append((f"全局下载[{index}]", button))
        return candidates

    async def _collect_download_buttons(self, page, *, include_body: bool) -> list[tuple[str, object]]:
        containers: list[tuple[str, object]] = [
            ("预览层", page.locator(_PREVIEW_CONTAINER_SELECTOR)),
        ]
        if include_body:
            containers.append(("全页面", page.locator("body")))

        candidates: list[tuple[str, object]] = []
        seen_boxes: set[tuple[int, int, int, int]] = set()
        for container_label, containers_locator in containers:
            try:
                container_count = await containers_locator.count()
            except Exception:
                continue
            for container_index in range(container_count - 1, -1, -1):
                container = containers_locator.nth(container_index)
                try:
                    if not await container.is_visible(timeout=500):
                        continue
                except Exception:
                    continue
                buttons = container.get_by_role("button", name="下载")
                try:
                    button_count = await buttons.count()
                except Exception:
                    continue
                for button_index in range(button_count - 1, -1, -1):
                    button = buttons.nth(button_index)
                    try:
                        if not await button.is_visible(timeout=500):
                            continue
                        box = await button.bounding_box(timeout=1_000)
                    except Exception:
                        continue
                    if box:
                        key = (
                            round(box["x"]),
                            round(box["y"]),
                            round(box["width"]),
                            round(box["height"]),
                        )
                        if key in seen_boxes:
                            continue
                        seen_boxes.add(key)
                    candidates.append((f"{container_label}[{container_index}]/下载[{button_index}]", button))
        return candidates

    async def _try_download_locator(self, page, button, output_path: Path, *, timeout_ms: int, label: str) -> bool:
        trigger_timeout = min(timeout_ms, _DOWNLOAD_TRIGGER_TIMEOUT_MS)
        try:
            async with page.expect_download(timeout=trigger_timeout) as download_info:
                await button.click(timeout=15_000)
            download = await download_info.value
            await download.save_as(str(output_path))
            logger.info("小云雀图片下载已触发: %s", label)
            return True
        except Exception as exc:
            logger.info("小云雀图片下载按钮未触发下载: %s error=%s", label, exc)
            return False

    async def _save_largest_preview_image(self, page, output_path: Path) -> bool:
        try:
            result = await page.evaluate(
                """async () => {
                    const isVisible = (el) => {
                        const rect = el.getBoundingClientRect();
                        const style = window.getComputedStyle(el);
                        return (
                            rect.width >= 240 &&
                            rect.height >= 160 &&
                            rect.bottom > 0 &&
                            rect.right > 0 &&
                            rect.top < window.innerHeight &&
                            rect.left < window.innerWidth &&
                            style.display !== "none" &&
                            style.visibility !== "hidden" &&
                            Number(style.opacity || "1") > 0.01
                        );
                    };
                    const images = Array.from(document.images)
                        .filter((img) => isVisible(img) && (img.naturalWidth || 0) > 0 && (img.naturalHeight || 0) > 0)
                        .map((img) => ({
                            img,
                            width: img.naturalWidth,
                            height: img.naturalHeight,
                            rect: img.getBoundingClientRect(),
                            src: img.currentSrc || img.src || "",
                        }))
                        .filter((item) => item.src && !item.src.startsWith("data:"))
                        .sort((a, b) => (b.width * b.height) - (a.width * a.height));
                    const target = images[0];
                    if (!target) return null;
                    const response = await fetch(target.src, { credentials: "include" });
                    if (!response.ok) {
                        return { error: `fetch ${response.status}`, width: target.width, height: target.height };
                    }
                    const blob = await response.blob();
                    const buffer = await blob.arrayBuffer();
                    const bytes = new Uint8Array(buffer);
                    let binary = "";
                    const chunkSize = 0x8000;
                    for (let i = 0; i < bytes.length; i += chunkSize) {
                        binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
                    }
                    return {
                        width: target.width,
                        height: target.height,
                        mime: blob.type,
                        base64: btoa(binary),
                    };
                }"""
            )
        except Exception as exc:
            logger.info("小云雀未能从预览图 src 直接保存: %s", exc)
            return False
        if not result or not isinstance(result, dict) or not result.get("base64"):
            logger.info("小云雀预览图 src 直接保存不可用: %s", result)
            return False
        try:
            output_path.write_bytes(base64.b64decode(str(result["base64"])))
        except Exception as exc:
            logger.info("小云雀预览图 src 写入失败: %s", exc)
            return False
        logger.info("小云雀已从预览图 src 直接保存图片: %sx%s", result.get("width"), result.get("height"))
        return True


class _playwright_context:
    def __init__(self, runner: XyqWebRunner) -> None:
        self.runner = runner
        self.playwright = None
        self.context = None

    async def __aenter__(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "缺少 Python Playwright 依赖，请先安装 playwright 并执行 playwright install chromium。"
            ) from exc

        self.runner.profile_dir.mkdir(parents=True, exist_ok=True)
        self.runner.download_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = await async_playwright().start()
        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.runner.profile_dir),
            headless=self.runner.headless,
            viewport={"width": 1440, "height": 900},
            accept_downloads=True,
            downloads_path=str(self.runner.download_dir),
            args=["--no-sandbox"],
        )
        restored_pages = list(self.context.pages)
        page = await self.context.new_page()
        await page.bring_to_front()
        for old_page in restored_pages:
            try:
                await old_page.close()
            except Exception:
                logger.info("小云雀关闭旧页面失败，继续使用新页面")
        page.set_default_timeout(30_000)
        return page

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.context is not None:
            await self.context.close()
        if self.playwright is not None:
            await self.playwright.stop()
