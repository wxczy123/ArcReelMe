"""小云雀网页自动化封装。

该模块把 ``https://xyq.jianying.com/`` 包成可被 image/video backend 调用的异步 runner。
它不处理登录流程，依赖 Playwright persistent profile 里已有登录态。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
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
_MIN_ACCEPTABLE_IMAGE_LONG_EDGE = 700
_HOME_URL = "https://xyq.jianying.com/home?from_page=xiaoyunque_landing_page&tab_name=home"
_XYQ_VIDEO_MODEL_MENU_PATTERNS: dict[str, str | re.Pattern[str]] = {
    XYQ_VIDEO_MODEL_SEEDANCE_2: re.compile(r"^Seedance 2\.0(?! Fast)"),
    XYQ_VIDEO_MODEL_SEEDANCE_2_FAST: "Seedance 2.0 Fast更快更便宜，经典基础版本，音视文图均可参考",
}


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


def _normalize_aspect_ratio(aspect_ratio: str | None) -> Literal["16:9", "9:16", "1:1"]:
    raw = (aspect_ratio or "").strip()
    if raw in {"16:9", "9:16", "1:1"}:
        return raw  # type: ignore[return-value]
    return "16:9" if raw.startswith("16") else "9:16"


def _normalize_duration(duration: int | None) -> int:
    if not duration:
        return 5
    return max(1, min(15, int(duration)))


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
            return await self._generate_video_locked(
                prompt=prompt,
                output_path=output_path,
                references=references or [],
                start_image=start_image,
                end_image=end_image,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
            )

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

    async def _generate_video_locked(
        self,
        *,
        prompt: str,
        output_path: Path,
        references: list[XyqReference],
        start_image: Path | None,
        end_image: Path | None,
        aspect_ratio: str,
        duration_seconds: int,
    ) -> Path:
        async with _playwright_context(self) as page:
            await self._goto_home(page)
            await page.get_by_role("button", name="沉浸式短片").click(timeout=20_000)
            await self._select_video_model(page)
            await self._select_aspect_ratio(page, aspect_ratio)
            await self._select_duration(page, duration_seconds)

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
                    await self._fill_prompt_with_refs(page, prompt, prepared)
                else:
                    await self._fill_prompt(page, prompt)

                await self._click_create(page)
                await self._download_result(page, output_path, media_kind="video")
        return output_path

    async def _goto_home(self, page) -> None:
        await page.goto(_HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        try:
            await page.wait_for_load_state("networkidle", timeout=5_000)
        except Exception:
            logger.info("小云雀页面 networkidle 等待超时，继续检查创作按钮")
        try:
            await page.get_by_role("button", name=re.compile("生成图片|沉浸式短片")).first.wait_for(timeout=30_000)
        except Exception as exc:
            raise RuntimeError("小云雀未进入创作首页，可能是登录态失效。请用同一 profile 手动登录后重试。") from exc

    async def _select_image_model(self, page) -> None:
        if self.model != XYQ_IMAGE_MODEL_SEEDREAM_4_AESTHETIC:
            logger.info("小云雀图片 model=%s 暂按 Seedream 4.0 美感版选择", self.model)
        await self._open_model_dropdown(page)
        await page.locator("div").filter(has_text="Seedream 4.0 美感版").nth(5).click(timeout=20_000)

    async def _select_video_model(self, page) -> None:
        pattern = _XYQ_VIDEO_MODEL_MENU_PATTERNS.get(self.model)
        if pattern is None:
            logger.warning("小云雀视频 model=%s 暂不支持页面选择，回退到 Seedance 2.0", self.model)
            pattern = _XYQ_VIDEO_MODEL_MENU_PATTERNS[XYQ_VIDEO_MODEL_SEEDANCE_2]
        await self._open_model_dropdown(page)
        await page.locator("div").filter(has_text=pattern).nth(5).click(timeout=20_000)

    async def _open_model_dropdown(self, page) -> None:
        try:
            await page.locator(".lucide.lucide-chevron-down").first.click(timeout=8_000)
        except Exception:
            await page.get_by_text(re.compile("Seedream|Seedance")).first.click(timeout=8_000)

    async def _select_aspect_ratio(self, page, aspect_ratio: str) -> None:
        ratio = _normalize_aspect_ratio(aspect_ratio)
        candidates = {
            "16:9": [":9（横屏）", "16:9（横屏）"],
            "9:16": [":16（竖屏）", "9:16（竖屏）"],
            "1:1": ["1:1", "方屏"],
        }[ratio]

        try:
            await page.locator(".trigger-Mt5lwU").first.click(timeout=8_000)
        except Exception:
            await page.get_by_role("menuitem", name=re.compile("9|16|1:1")).first.click(timeout=8_000)

        for text in candidates:
            try:
                await page.locator("div").filter(has_text=text).last.click(timeout=5_000)
                return
            except Exception:
                continue
        logger.warning("小云雀未能切换比例到 %s，继续使用页面当前比例", ratio)

    async def _select_duration(self, page, duration_seconds: int) -> None:
        duration = _normalize_duration(duration_seconds)
        try:
            await page.get_by_role("button", name="向右滚动配置项").click(timeout=3_000)
        except Exception:
            pass
        try:
            await page.get_by_role("button", name="秒").click(timeout=8_000)
            spin = page.get_by_role("spinbutton", name="秒")
            await spin.fill(str(duration), timeout=8_000)
        except Exception:
            logger.warning("小云雀未能设置视频时长 %s 秒，继续使用页面当前时长", duration)
        try:
            await page.get_by_role("button", name="向左滚动配置项").click(timeout=3_000)
        except Exception:
            pass

    async def _select_video_reference_mode(self, page, mode: Literal["全能参考", "首尾帧"]) -> None:
        names = ("全能参考", "首尾帧")
        opened = False
        for name in names:
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

    async def _upload_references(self, page, references: list[_PreparedReference]) -> None:
        if not references:
            return
        await page.get_by_role("button", name="上传参考素材").click(timeout=20_000)
        for ref in references:
            await self._upload_one_reference(page, ref)
            await self._wait_reference_uploaded(page, ref)
            await page.wait_for_timeout(800)

    async def _upload_one_reference(self, page, ref: _PreparedReference) -> None:
        file_input = page.locator("input[type=file]").last
        try:
            await file_input.set_input_files(str(ref.staged_path), timeout=5_000)
            return
        except Exception:
            logger.info("小云雀未能直接设置 file input，改用 file chooser 上传: %s", ref.staged_path.name)

        local_upload = page.get_by_role("button", name=re.compile("本地上传")).last
        async with page.expect_file_chooser(timeout=20_000) as chooser_info:
            await local_upload.click(timeout=20_000)
        file_chooser = await chooser_info.value
        await file_chooser.set_files(str(ref.staged_path), timeout=20_000)

    async def _wait_reference_uploaded(self, page, ref: _PreparedReference) -> None:
        candidates = [
            page.get_by_role("button", name=ref.display_name),
            page.get_by_role("button", name=re.compile(re.escape(ref.staged_path.name))),
            page.get_by_text(ref.staged_path.name, exact=False),
        ]
        for locator in candidates:
            try:
                await locator.last.wait_for(timeout=15_000)
                return
            except Exception:
                continue
        logger.warning("小云雀上传素材后未确认出现在素材列表: %s", ref.staged_path.name)

    async def _fill_prompt(self, page, prompt: str) -> None:
        editor = page.locator(".tiptap")
        await editor.click(timeout=20_000)
        await editor.fill((prompt or "").strip(), timeout=20_000)

    async def _fill_prompt_with_refs(self, page, prompt: str, references: list[_PreparedReference]) -> None:
        text = (prompt or "").strip()
        editor = page.locator(".tiptap")
        await editor.click(timeout=20_000)
        await editor.fill(text, timeout=20_000)
        for idx, ref in enumerate(references, start=1):
            await self._open_reference_mention_menu(page)
            await self._select_uploaded_reference(page, ref, ordinal=idx)

    async def _open_reference_mention_menu(self, page) -> None:
        await page.locator(".tiptap").click(timeout=20_000)
        await page.keyboard.press("End")
        await page.keyboard.insert_text("\n@")
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
            await page.get_by_role("img", name="image").last.click(timeout=20_000)
            await page.wait_for_timeout(800)
        if media_kind == "image":
            await self._download_image_result(page, output_path, timeout_ms)
            return
        await self._download_by_button(page, output_path, timeout_ms=timeout_ms, button_index=-1)

    async def _download_by_button(self, page, output_path: Path, *, timeout_ms: int, button_index: int) -> None:
        async with page.expect_download(timeout=timeout_ms) as download_info:
            download_button = page.get_by_role("button", name="下载")
            if button_index < 0:
                await download_button.last.click(timeout=timeout_ms)
            else:
                await download_button.nth(button_index).click(timeout=timeout_ms)
        download = await download_info.value
        await download.save_as(str(output_path))

    async def _download_image_result(self, page, output_path: Path, timeout_ms: int) -> None:
        download_buttons = page.get_by_role("button", name="下载")
        button_count = await download_buttons.count()
        candidates = list(range(button_count - 1, -1, -1)) or [-1]
        last_size: tuple[int, int] | None = None
        for index in candidates[:3]:
            await self._download_by_button(page, output_path, timeout_ms=timeout_ms, button_index=index)
            last_size = _read_image_size(output_path)
            if not _is_low_resolution_image(output_path):
                return
            output_path.unlink(missing_ok=True)
            logger.warning("小云雀下载到低清图片 %s，尝试其他下载按钮", last_size)
        raise RuntimeError(f"小云雀下载结果疑似缩略图，已拒绝保存。最后尺寸: {last_size}")


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
