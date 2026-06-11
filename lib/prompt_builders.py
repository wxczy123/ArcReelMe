"""图像 / 视频 / 资产 prompt 的统一真相源。

WebUI（server/services/generation_tasks.py）和 Skill（agent_runtime_profile/.claude/skills/generate-assets）
都从这里取最终 prompt 文本，确保入口一致、不漂移。

设计要点：
- 无 backend 锁定：纯文本拼接，由调用方决定走哪个 image/video provider。
- 资产图 prompt 保持自然语言和低噪声，不拼工程字段标签，不堆泛化防崩短语。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 内部常量：布局 / 风格前缀
# ---------------------------------------------------------------------------

_CHARACTER_FULL_BODY_LAYOUT = "单人全身参考图，角色从头到脚完整入画，纯白色背景，不要文字。"
_CHARACTER_GROUP_LAYOUT = (
    "群体参考图，多名成员完整入画，展示群体服饰体系、整体外貌特征、自然个体差异和常见站位队形。纯净浅色背景，不要文字。"
)
_CHARACTER_THREE_VIEW_LAYOUT = "三视图角色参考图，纯净浅色背景，横向并列展示同一角色的正面、侧面、背面全身 A-Pose。"
_PROP_LAYOUT = "三视图水平排列于纯净浅灰背景：左侧正面全视图、中间 45° 侧视图体现立体感、右侧关键细节特写。"
_PROP_GUARD = "外观结构完整，焦点清晰。"

_NEGATIVE_TAIL_VIDEO = "禁止出现：背景音乐、血迹、文字字幕、水印。"


def _style_prefix(style: str = "", style_description: str = "") -> str:
    """组合视觉风格前缀。两者都为空时返回空串。"""
    parts = []
    if style:
        parts.append(style if style.startswith("画风：") else f"画风：{style}")
    if style_description:
        parts.append(f"描述：{style_description}")
    if not parts:
        return ""
    return "\n".join(parts) + "\n\n"


def _join_descriptions(*parts: str) -> str:
    """合并多段描述，去掉空段，不添加工程标签。"""
    return "".join(part.strip() for part in parts if part and part.strip())


# ---------------------------------------------------------------------------
# 资产 prompt（character / scene / prop）
# ---------------------------------------------------------------------------


def build_character_full_body_prompt(
    name: str,
    description: str,
    form_label: str = "",
    form_description: str = "",
    style: str = "",
    style_description: str = "",
    character_kind: str = "single",
) -> str:
    """角色全身主参考图 prompt；群体角色使用群体参考图布局。"""
    style_block = _style_prefix(style, style_description)
    character_text = _join_descriptions(description, form_description)
    if character_kind == "group":
        return f"{style_block}角色群体「{name}」参考图。\n\n{character_text}\n\n{_CHARACTER_GROUP_LAYOUT}"
    return f"{style_block}角色「{name}」单人全身参考图。\n\n{character_text}\n\n{_CHARACTER_FULL_BODY_LAYOUT}"


def build_character_three_view_prompt(
    name: str,
    description: str,
    form_label: str = "",
    form_description: str = "",
    style: str = "",
    style_description: str = "",
    character_kind: str = "single",
) -> str:
    """角色三视图 prompt。"""
    style_block = _style_prefix(style, style_description)
    character_text = _join_descriptions(description, form_description)
    if character_kind == "group":
        return (
            f"{style_block}"
            f"角色群体「{name}」一致性参考图。\n\n"
            f"{character_text}\n\n"
            f"横向展示多名代表成员，体现群体服饰体系、整体外貌特征和自然个体差异。"
            f"纯净浅色背景，不要文字。"
        )
    return (
        f"{style_block}"
        f"角色「{name}」的三视图一致性参考图。\n\n"
        f"{character_text}\n\n"
        f"{_CHARACTER_THREE_VIEW_LAYOUT}\n\n"
        f"不要文字。"
    )


def build_character_prompt(name: str, description: str, style: str = "", style_description: str = "") -> str:
    """旧接口：默认生成单人全身主参考图。"""
    return build_character_full_body_prompt(name, description, "", "", style, style_description)


def build_scene_prompt(name: str, description: str, style: str = "", style_description: str = "") -> str:
    """场景设计图 prompt。"""
    style_block = _style_prefix(style, style_description)
    return f"{style_block}标志性场景「{name}」的视觉参考。\n\n{description}"


def build_prop_prompt(name: str, description: str, style: str = "", style_description: str = "") -> str:
    """道具设计图 prompt（三视图）。"""
    style_block = _style_prefix(style, style_description)
    return f"{style_block}道具「{name}」的多视角展示。\n\n{description}\n\n{_PROP_LAYOUT}\n\n{_PROP_GUARD}"


# ---------------------------------------------------------------------------
# 分镜 / 视频 prompt 末尾增强
# ---------------------------------------------------------------------------


def append_video_negative_tail(prompt: str) -> str:
    """给视频生成 prompt 追加统一的反向提示词。

    调用方拿到分镜 video_prompt 文本后，在交给 video backend 之前过一遍此函数；
    避免在每个 caller 各自拼接、导致漂移。
    """
    if not prompt or not prompt.strip():
        return _NEGATIVE_TAIL_VIDEO
    if _NEGATIVE_TAIL_VIDEO in prompt:
        return prompt
    return f"{prompt.rstrip()}\n\n{_NEGATIVE_TAIL_VIDEO}"


def build_storyboard_suffix(content_mode: str = "narration", *, aspect_ratio: str | None = None) -> str:
    """分镜图构图后缀。优先 aspect_ratio，缺省按 content_mode 推导。"""
    if aspect_ratio is None:
        ratio = "9:16" if content_mode == "narration" else "16:9"
    else:
        ratio = aspect_ratio
    if ratio == "9:16":
        return "竖屏构图。"
    if ratio == "16:9":
        return "横屏构图。"
    return ""
