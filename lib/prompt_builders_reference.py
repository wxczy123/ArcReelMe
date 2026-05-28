"""参考生视频模式 Prompt 构建器。

设计原则与 prompt_builders_script.py 一致：
- 不重复 schema 已声明的枚举（type 等）；让 response_schema 直接约束。
- 多选枚举字段不在 prompt 里写"如何选"判据；让模型按画面内容自行决定。
- 字段说明给指导和 example，不堆"必须 / 禁止"清单。
- 跨 backend 时长 / references 上限通过参数显式注入，不在文本里硬编码秒数。
"""

from __future__ import annotations


def _format_asset_names(assets: dict | None) -> str:
    if not assets:
        return "（无）"
    return "\n".join(
        f"- {name}: {meta.get('description', '') if isinstance(meta, dict) else ''}" for name, meta in assets.items()
    )


def _format_character_forms(characters: dict | None) -> str:
    if not characters:
        return "（无）"
    lines: list[str] = []
    for name, data in characters.items():
        if not isinstance(data, dict):
            lines.append(f"- {name}")
            continue
        desc = data.get("description") or ""
        default_form = data.get("default_form") or "default"
        forms = data.get("forms") if isinstance(data.get("forms"), dict) else {}
        if not forms:
            lines.append(f"- {name}: {desc}\n  default_form: {default_form}\n  forms: default（默认造型）")
            continue
        form_bits: list[str] = []
        for form_id, form in forms.items():
            if isinstance(form, dict):
                label = form.get("label") or form_id
                form_desc = form.get("description") or ""
                default_mark = "，默认" if form_id == default_form else ""
                form_bits.append(f"{form_id}（{label}：{form_desc}{default_mark}）")
            else:
                form_bits.append(str(form_id))
        lines.append(f"- {name}: {desc}\n  default_form: {default_form}\n  forms: " + "；".join(form_bits))
    return "\n".join(lines)


def build_reference_video_prompt(
    *,
    project_overview: dict,
    style: str,
    style_description: str,
    characters: dict,
    scenes: dict,
    props: dict,
    units_md: str,
    supported_durations: list[int],
    max_refs: int,
    episode: int,
    max_duration: int | None = None,
    aspect_ratio: str = "9:16",
    target_language: str = "中文",
) -> str:
    """构建参考生视频模式的 LLM Prompt。

    Args:
        project_overview: 项目概述（synopsis, genre, theme, world_setting）。
        style / style_description: 视觉风格标签与描述。
        characters / scenes / props: 三类已注册资产字典（用于候选列表）。
        units_md: `step1_reference_units.md` 内容（subagent 输出）。
        supported_durations: 当前视频模型支持的单镜头时长列表（秒）。
        max_refs: 当前视频模型支持的最大参考图数。
        max_duration: 当前视频模型的单次生成时长上限（秒）。传入时 prompt 会显式
            声明硬上限；unit 实际时长应继承 step1，不在本阶段重新扩写或压缩。
    """
    character_names = list(characters.keys())
    scene_names = list(scenes.keys())
    prop_names = list(props.keys())

    durations_desc = "/".join(str(d) for d in supported_durations) + "s"
    max_duration_line = (
        f"\n   - unit 内所有 Shot `duration` 之和不得超过 {max_duration} 秒（当前模型上限）。"
        f"本阶段只结构化 step1 已给出的时长，不为了贴近上限而增删 shot 或改写文本。"
        if max_duration is not None
        else ""
    )

    return f"""# 角色与任务

你是一位资深的短视频分镜编剧，本任务是为「参考生视频」模式产出 JSON 剧本。
你的任务：基于下方 step1_units 表，按 schema 产出 ReferenceVideoScript。
这是结构化转换任务，不是二次创作任务。

**输出语言**：所有字符串值必须使用 {target_language}；JSON 键名 / 枚举值保持英文。
**结构约束**：字段 / 枚举 / 必填项由 response_schema 强制；本提示只解释**如何写好每个字段**。

# 上下文

<overview>
{project_overview.get("synopsis", "")}

题材：{project_overview.get("genre", "")}
主题：{project_overview.get("theme", "")}
世界观：{project_overview.get("world_setting", "")}
</overview>

<style>
风格：{style}
描述：{style_description}
画面比例：{aspect_ratio}
</style>

<characters>
{_format_character_forms(characters)}
</characters>

<scenes>
{_format_asset_names(scenes)}
</scenes>

<props>
{_format_asset_names(props)}
</props>

<step1_units>
{units_md}
</step1_units>

<episode_constraints>
当前正在生成第 {episode} 集。本集所有 unit_id 必须严格使用 `E{episode}U{{两位序号}}` 格式（如 E{episode}U01、E{episode}U02），不得使用其他集号前缀。
若 step1_units 表里出现非 `E{episode}` 前缀（如 E1U..），视为脏数据，请按当前集号 `E{episode}` 重写。
</episode_constraints>

# 字段写作指引

对每个 video_unit，按下列要求填写字段：

a. **unit_id**：保留 step1 中的 `E{episode}U{{两位序号}}`（当前为第 {episode} 集），例如 `E{episode}U01`，不要改成 `E{episode}U1`。

b. **shots**：1-5 个 Shot。
   - `duration`：整数秒，取值必须在当前模型支持列表中：{durations_desc}。{max_duration_line}
   - `text`：必须继承 step1_units 中“完整 shot 文本”的原文。不要摘要、压缩、润色、删短或重写镜头描述。
     保留镜头语言、动作细节、可见表情、对白、自述、有明确来源的画外音、内心OS、系统面板文字、声音提示。
     只允许做最小格式清理：去掉 Markdown 列表符号、修正明显多余空白、确保 JSON 字符串合法。
     如果 step1 原文里有旁白、外貌 / 服装 / 场景细节，本阶段不要自行删除或改写；需要内容修改应回到 step1 重做。
   - 单 unit 内所有 Shot `duration` 之和即该 unit `duration_seconds`。

c. **references**：按顺序决定 `[图N]` 编号。
   - `name` 必须来自候选：
     - character: {", ".join(character_names) or "（无）"}
     - scene: {", ".join(scene_names) or "（无）"}
     - prop: {", ".join(prop_names) or "（无）"}
   - character reference 必须填写 `form_id`，值来自上方该角色的 forms；没有明确特殊造型时使用该角色的 default_form。
     好例：`{{"type":"character","name":"角色A","form_id":"default"}}`。
   - scene / prop reference 不填写 `form_id`。
   - 每个 shot `text` 中出现的 `@名称` 都要在 references 注册一次。
   - **references 数量不超过 {max_refs}**（模型上限）；超出时把次要角色合并到背景描述。

d. **duration_seconds**：所有 shot `duration` 之和；不要手动覆盖。

# 顶层字段

- `episode` / `title` / `summary` / `novel.title` / `novel.chapter` 必填。
- `generation_mode` 固定 "reference_video"（由 caller 注入，不需 LLM 填）。
- `duration_seconds` 可先写 0，由 caller 重算。

# 复核

- 每 unit 最多 5 个 shot；shot 数、shot 顺序、shot 时长、shot text 应与 step1_units 的“完整 shot 文本”一致。
- `@名称` 只能引用 characters / scenes / props 三表中已注册的名字；character reference 的 form_id 只能来自该角色 forms。
- 不要把 step1 的完整 shot 文本改写成摘要句；不要删除对白、自述、有明确来源的画外音、OS、系统文字或声音提示。
- 不要发明新资产。

请按 step1_units 顺序逐 unit 产出。
"""
