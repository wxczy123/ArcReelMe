"""小云雀网页图片 backend。"""

from __future__ import annotations

import logging
from pathlib import Path

from lib.image_backends.base import (
    ImageCapability,
    ImageGenerationRequest,
    ImageGenerationResult,
)
from lib.web_automation.xyq import (
    XYQ_IMAGE_MODEL_SEEDREAM_4_AESTHETIC,
    XYQ_PROVIDER_ID,
    XyqReference,
    XyqWebRunner,
)

logger = logging.getLogger(__name__)


class XyqWebImageBackend:
    """通过 Playwright 操作小云雀网页生成图片。"""

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
        self._model = model or XYQ_IMAGE_MODEL_SEEDREAM_4_AESTHETIC
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
    def capabilities(self) -> set[ImageCapability]:
        return {ImageCapability.TEXT_TO_IMAGE, ImageCapability.IMAGE_TO_IMAGE}

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        references = [XyqReference(path=Path(ref.path), label=ref.label) for ref in request.reference_images or []]
        if references:
            logger.info("小云雀图片生成使用 %d 张参考图", len(references))
        await self._runner.generate_image(
            prompt=request.prompt,
            output_path=request.output_path,
            references=references,
            aspect_ratio=request.aspect_ratio,
        )
        return ImageGenerationResult(
            image_path=request.output_path,
            provider=XYQ_PROVIDER_ID,
            model=self._model,
            seed=request.seed,
        )
