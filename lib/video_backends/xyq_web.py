"""小云雀网页视频 backend。"""

from __future__ import annotations

import logging
from pathlib import Path

from lib.video_backends.base import (
    VideoCapabilities,
    VideoCapability,
    VideoGenerationRequest,
    VideoGenerationResult,
)
from lib.web_automation.xyq import (
    XYQ_MAX_REFERENCE_IMAGES,
    XYQ_PROVIDER_ID,
    XYQ_VIDEO_MODEL_SEEDANCE_2,
    XYQ_VIDEO_MODEL_SEEDANCE_2_FAST,
    XyqReference,
    XyqWebRunner,
)

__all__ = ["XyqWebVideoBackend", "XYQ_VIDEO_MODEL_SEEDANCE_2", "XYQ_VIDEO_MODEL_SEEDANCE_2_FAST"]

logger = logging.getLogger(__name__)


class XyqWebVideoBackend:
    """通过 Playwright 操作小云雀网页生成视频。"""

    def __init__(
        self,
        *,
        model: str | None = None,
        profile_dir: str | None = None,
        download_dir: str | None = None,
        headless: str | bool | None = None,
        timeout_seconds: str | int | None = None,
        **_: object,
    ) -> None:
        self._model = model or XYQ_VIDEO_MODEL_SEEDANCE_2
        self._runner = XyqWebRunner(
            model=self._model,
            profile_dir=profile_dir,
            download_dir=download_dir,
            headless=headless,
            timeout_seconds=timeout_seconds,
        )

    @property
    def name(self) -> str:
        return XYQ_PROVIDER_ID

    @property
    def model(self) -> str:
        return self._model

    @property
    def capabilities(self) -> set[VideoCapability]:
        return {VideoCapability.TEXT_TO_VIDEO, VideoCapability.IMAGE_TO_VIDEO}

    @property
    def video_capabilities(self) -> VideoCapabilities:
        return VideoCapabilities(
            first_frame=True,
            last_frame=True,
            reference_images=True,
            max_reference_images=XYQ_MAX_REFERENCE_IMAGES,
        )

    async def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        references = [XyqReference(path=Path(ref)) for ref in request.reference_images or []]
        if len(references) > XYQ_MAX_REFERENCE_IMAGES:
            logger.warning("小云雀参考图数量 %d 超过上限 %d，截断", len(references), XYQ_MAX_REFERENCE_IMAGES)
            references = references[:XYQ_MAX_REFERENCE_IMAGES]
        await self._runner.generate_video(
            prompt=request.prompt,
            output_path=request.output_path,
            references=references,
            start_image=request.start_image,
            end_image=request.end_image,
            aspect_ratio=request.aspect_ratio,
            duration_seconds=request.duration_seconds,
        )
        return VideoGenerationResult(
            video_path=request.output_path,
            provider=XYQ_PROVIDER_ID,
            model=self._model,
            duration_seconds=request.duration_seconds,
            seed=request.seed,
            generate_audio=False,
        )
