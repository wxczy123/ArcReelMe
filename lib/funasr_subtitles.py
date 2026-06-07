"""FunASR subtitle transcription helpers."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MODEL: Any | None = None
_PUNCTUATION = set("，。！？；：,.!?;:")
_STRONG_PUNCTUATION = set("。！？!?；;")


@dataclass(frozen=True)
class SubtitleCue:
    """一条可写入剪映文本轨的字幕。时间单位为微秒。"""

    start_us: int
    end_us: int
    text: str


def transcribe_video_to_cues(video_path: Path, *, max_chars: int = 22) -> list[SubtitleCue]:
    """Use FunASR to transcribe a video file into timestamped subtitle cues."""
    if not video_path.exists():
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    with tempfile.TemporaryDirectory(prefix="arcreel_funasr_") as tmp:
        audio_path = Path(tmp) / "audio.wav"
        _extract_wav(video_path, audio_path)
        result = _get_model().generate(
            input=str(audio_path),
            batch_size_s=300,
            batch_size_threshold_s=60,
            sentence_timestamp=True,
        )

    return _result_to_cues(result, max_chars=max_chars)


def _extract_wav(video_path: Path, audio_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise ValueError("未找到 ffmpeg，无法从视频提取音频用于 FunASR 字幕识别")

    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            str(audio_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise ValueError(f"提取视频音频失败: {detail}")


def _get_model() -> Any:
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    try:
        import torch
        from funasr import AutoModel
    except ImportError as exc:
        raise ValueError("FunASR 未安装完整，请先安装 funasr、modelscope、torch 和 torchaudio") from exc

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    logger.info("初始化 FunASR 模型: device=%s", device)
    _MODEL = AutoModel(
        model="paraformer-zh",
        vad_model="fsmn-vad",
        vad_kwargs={"max_single_segment_time": 30000},
        punc_model="ct-punc",
        device=device,
        disable_update=True,
    )
    return _MODEL


def _result_to_cues(result: Any, *, max_chars: int) -> list[SubtitleCue]:
    items = result if isinstance(result, list) else [result]
    cues: list[SubtitleCue] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        sentence_cues = _sentence_info_to_cues(item.get("sentence_info"))
        if sentence_cues:
            cues.extend(sentence_cues)
            continue

        text = str(item.get("text") or "").strip()
        timestamps = item.get("timestamp")
        if text and isinstance(timestamps, list):
            cues.extend(_char_timestamps_to_cues(text, timestamps, max_chars=max_chars))

    return _normalize_cues(cues)


def _sentence_info_to_cues(sentence_info: Any) -> list[SubtitleCue]:
    if not isinstance(sentence_info, list):
        return []

    cues: list[SubtitleCue] = []
    for sentence in sentence_info:
        if not isinstance(sentence, dict):
            continue
        text = str(sentence.get("text") or "").strip()
        start = sentence.get("start")
        end = sentence.get("end")
        if not text or not isinstance(start, int | float) or not isinstance(end, int | float):
            continue
        cues.append(SubtitleCue(start_us=int(start * 1000), end_us=int(end * 1000), text=text))
    return cues


def _char_timestamps_to_cues(text: str, timestamps: list[Any], *, max_chars: int) -> list[SubtitleCue]:
    chars = [char for char in text if not char.isspace()]
    if not chars:
        return []

    normalized_timestamps = [_normalize_timestamp(item) for item in timestamps]
    normalized_timestamps = [item for item in normalized_timestamps if item is not None]
    if not normalized_timestamps:
        return []

    timestamped_chars = _align_timestamps(chars, normalized_timestamps)
    cues: list[SubtitleCue] = []
    buffer: list[str] = []
    start_ms: int | None = None
    end_ms: int | None = None

    def flush() -> None:
        nonlocal buffer, start_ms, end_ms
        text_value = "".join(buffer).strip()
        if text_value and start_ms is not None and end_ms is not None and end_ms > start_ms:
            cues.append(SubtitleCue(start_us=start_ms * 1000, end_us=end_ms * 1000, text=text_value))
        buffer = []
        start_ms = None
        end_ms = None

    for char, timestamp in timestamped_chars:
        if not char:
            continue
        buffer.append(char)
        if timestamp is not None:
            char_start, char_end = timestamp
            start_ms = char_start if start_ms is None else start_ms
            end_ms = max(end_ms or char_end, char_end)

        visible_len = len(_strip_punctuation("".join(buffer)))
        if char in _STRONG_PUNCTUATION or (visible_len >= max_chars and char in _PUNCTUATION):
            flush()
        elif visible_len >= max_chars + 6 and timestamp is not None:
            flush()

    flush()
    return cues


def _normalize_timestamp(value: Any) -> tuple[int, int] | None:
    if (
        isinstance(value, list | tuple)
        and len(value) >= 2
        and isinstance(value[0], int | float)
        and isinstance(value[1], int | float)
    ):
        start = max(0, int(value[0]))
        end = max(start + 1, int(value[1]))
        return start, end
    return None


def _align_timestamps(
    chars: list[str],
    timestamps: list[tuple[int, int]],
) -> list[tuple[str, tuple[int, int] | None]]:
    if len(timestamps) >= len(chars):
        return [(char, timestamps[index] if index < len(timestamps) else None) for index, char in enumerate(chars)]

    aligned: list[tuple[str, tuple[int, int] | None]] = []
    timestamp_index = 0
    last_timestamp: tuple[int, int] | None = None
    for char in chars:
        if char in _PUNCTUATION:
            aligned.append((char, last_timestamp))
            continue
        timestamp = timestamps[timestamp_index] if timestamp_index < len(timestamps) else last_timestamp
        aligned.append((char, timestamp))
        if timestamp is not None:
            last_timestamp = timestamp
        timestamp_index += 1
    return aligned


def _strip_punctuation(text: str) -> str:
    return re.sub(r"[，。！？；：,.!?;:\s]", "", text)


def _normalize_cues(cues: list[SubtitleCue]) -> list[SubtitleCue]:
    normalized: list[SubtitleCue] = []
    last_end = 0
    for cue in sorted(cues, key=lambda item: (item.start_us, item.end_us)):
        text = cue.text.strip()
        if not text:
            continue
        start = max(0, int(cue.start_us), last_end)
        end = max(start + 100_000, int(cue.end_us))
        normalized.append(SubtitleCue(start_us=start, end_us=end, text=text))
        last_end = end
    return normalized
