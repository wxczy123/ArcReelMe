---
name: generate-assets
description: "统一资产生成 skill：场景/道具用 generate_assets；角色形态参考图用 generate_character_refs。当用户说生成角色图、场景图、道具图或有资产缺图时使用。"
---

# 生成资产设计图

为项目的角色形态、场景、道具创建参考设计图，保证整个视频中视觉元素的一致性。
图像供应商由项目设置选择（不锁定具体 backend）。

> Prompt 编写原则详见 `.claude/references/generation-modes.md` 的"Prompt 语言"章节。

## 共同约定

- 所有资产 `description` 用**叙事式段落**，而不是关键词列表。
- 用户只需在 project.json 中维护 `description`；最终交给图像 backend 的完整 prompt
  （含布局 / 防崩短语 / 反向提示词）由 `lib/prompt_builders.py` 在 server 端拼好，
  WebUI 与 Skill 走同一份真相源。
- Pending 判定：
  - 角色：`forms.*.refs.full_body.path` 或 `forms.*.refs.three_view.path` 为空或文件不存在
  - 场景/道具：对应资产的 `*_sheet` 字段为空或文件不存在

---

## 角色（character forms）

### description 编写指南

角色由多个形态组成。顶层 description 写跨形态稳定外貌；每个 form.description 写该形态的服装、状态和视觉差异。

**示例**：

> "二十出头的女子，身材纤细，鹅蛋脸上有一双清澈的杏眼，柳叶眉微蹙时带着几分忧郁。身着淡青色绣花罗裙，腰间系着同色丝带，显得端庄而不失灵动。"

### 输出布局

每个形态固定生成两个槽位：
- `full_body`：单人全身主参考图，可用于生成三视图或由用户设为分镜参考
- `three_view`：正面 / 侧面 / 背面三视图，默认喂给分镜 / 参考生视频，也用于一致性审阅

> 用户填写 description 时只需关心外貌 / 服装等内容；布局由 builder 注入。

---

## 场景（scene）

### description 编写指南

用连贯段落描述形态、光线、氛围，突出能跨场景识别的独特特征。

**示例**：

> "村口的百年老槐树，树干粗壮需三人合抱，树皮龟裂沧桑。主干上有一道明显的雷击焦痕，从顶部蜿蜒而下。树冠茂密，夏日里洒下斑驳的树影。"

---

## 道具（prop）

### description 编写指南

用连贯段落描述形态、质感、细节，突出能跨场景识别的独特特征。

**示例**：

> "一块翠绿色的祖传玉佩，约拇指大小，玉质温润透亮。表面雕刻着精致的莲花纹样，花瓣层层舒展。玉佩上系着一根红色丝绳，打着传统的中国结。"

### 输出布局

三视图水平排列于纯净浅灰背景：正面全视图、45° 侧视图、关键细节特写。

---

## 工具调用

入队走 MCP 工具：

| 操作 | 工具 |
|------|------|
| 列出角色 pending | `mcp__arcreel__list_pending_character_refs({})` |
| 生成角色 pending | `mcp__arcreel__generate_character_refs({})` |
| 生成当前集实际使用的角色形态 | `mcp__arcreel__generate_character_refs({"current_episode_only": true, "script_file": "episode_1.json"})` |
| 生成指定角色形态槽位 | `mcp__arcreel__generate_character_refs({"targets":[{"character":"苏洄","form_id":"default","slots":["full_body","three_view"]}]})` |
| 列出场景/道具 pending | `mcp__arcreel__list_pending_assets({"type": "scene"})`（type 可省略） |
| 生成场景/道具 pending | `mcp__arcreel__generate_assets({})` |
| 生成某类全部 pending | `mcp__arcreel__generate_assets({"type": "scene"})` |
| 生成指定多个 | `mcp__arcreel__generate_assets({"type": "prop", "names": ["玉佩", "密信"]})` |
| 生成单个 | `mcp__arcreel__generate_assets({"type": "scene", "names": ["村口老槐树"]})` |

返回 `is_error: true` 时，文本里包含失败明细，按需重试或反馈给开发者。

## 工作流程

1. **加载项目元数据** — 从 project.json 找出缺少角色形态槽位或 `*_sheet` 的资产
2. **入队生成任务** — description 直接作为 prompt 提交；server 端 `lib.prompt_builders` 注入布局 / 防崩 / 反向
3. **审核检查点** — 展示每张设计图，用户可批准或要求重新生成
4. **更新 project.json** — 角色更新 `forms.*.refs.*.path`；场景/道具更新 `scene_sheet` / `prop_sheet`

## 质量检查

- **角色 full_body**：单人全身完整入画，无分格、无第二个人、身体不裁切
- **角色 three_view**：正面/侧面/背面为同一造型，面部、发型、服装、配饰一致
- **场景**：整体构图和标志性特征突出、光线氛围合适、细节图清晰
- **道具**：三个视角清晰一致、细节符合描述、特殊纹理清晰可见
