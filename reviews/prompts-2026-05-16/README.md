# ArcReel 当前提示词来源备份

日期：2026-05-16

本目录用于集中查看当前 ArcReel 原版流程中会影响生成质量的提示词、Agent 指令、Skill 指令和 prompt builder。这里保存的是源码级提示词来源；真正运行时的最终 prompt 还会拼入项目标题、小说内容、角色/场景/道具、风格、剧本字段、模型能力等动态数据。

## 1. Agent 总体行为

- `agent_runtime_profile/CLAUDE.md`
  - Agent 工作空间总规则、生成模式、目录结构、工作流概览。
- `server/agent_runtime/session_manager.py`
  - 后端构造 ArcReel 智能体系统提示词的位置。
- `server/agent_runtime/turn_schema.py`
  - 对话历史 turn 的结构说明。

## 2. Agent / Subagent 指令

- `agent_runtime_profile/.claude/agents/analyze-assets.md`
  - 从小说中提取角色、场景、道具。
- `agent_runtime_profile/.claude/agents/split-narration-segments.md`
  - 说书模式下按朗读节奏拆片段。
- `agent_runtime_profile/.claude/agents/normalize-drama-script.md`
  - 剧集动画模式下把小说改写/规范化为单集剧本中间稿。
- `agent_runtime_profile/.claude/agents/split-reference-video-units.md`
  - 参考生视频模式下拆 video unit。
- `agent_runtime_profile/.claude/agents/create-episode-script.md`
  - 把中间稿转成最终 episode_N.json。
- `agent_runtime_profile/.claude/agents/generate-assets.md`
  - 资产、分镜、视频生成类任务的 subagent 指令。

## 3. Slash Skill 指令

- `agent_runtime_profile/.claude/skills/manga-workflow/SKILL.md`
  - `/视频工作流`，端到端流程编排。
- `agent_runtime_profile/.claude/skills/manage-project/SKILL.md`
  - 项目管理、分集切分等确定性流程。
- `agent_runtime_profile/.claude/skills/generate-script/SKILL.md`
  - 剧本生成入口说明。
- `agent_runtime_profile/.claude/skills/generate-assets/SKILL.md`
  - 角色/场景/道具设计图生成说明。
- `agent_runtime_profile/.claude/skills/generate-storyboard/SKILL.md`
  - 分镜图生成说明。
- `agent_runtime_profile/.claude/skills/generate-grid/SKILL.md`
  - 宫格图生成说明。
- `agent_runtime_profile/.claude/skills/generate-video/SKILL.md`
  - 视频片段生成说明。
- `agent_runtime_profile/.claude/skills/generate-video/references/veo_prompts.md`
  - Veo 视频提示词参考。
- `agent_runtime_profile/.claude/skills/compose-video/SKILL.md`
  - ffmpeg 合成、加 BGM、片头片尾说明。

## 4. 后端真实 Prompt Builder

- `lib/prompt_builders.py`
  - 角色、场景、道具、分镜、视频等媒体生成 prompt 拼装。
- `lib/prompt_builders_script.py`
  - 说书/剧集动画模式的结构化剧本生成 prompt。
- `lib/prompt_builders_reference.py`
  - 参考生视频模式的 JSON 剧本生成 prompt。
- `lib/grid/prompt_builder.py`
  - 宫格图 prompt 拼装。
- `lib/prompt_rules/episode_pacing.py`
  - 剧集节奏规则片段。
- `lib/prompt_utils.py`
  - 结构化 image_prompt / video_prompt 转文本工具。
- `lib/script_generator.py`
  - 调用文本模型生成剧本的组织逻辑。
- `lib/text_backends/prompts.py`
  - 文本后端通用 prompt 常量。
- `lib/style_templates.py`
  - 风格模板定义，会进入图片/视频生成上下文。

## 5. 生成模式参考

- `agent_runtime_profile/.claude/references/generation-modes.md`
  - 图生视频、宫格生视频、参考生视频三种模式的数据路径和 prompt 语言约定。

## 备注

- 这些文件是 2026-05-16 当前工作区版本的快照。
- 如果后续改代码，这里的备份不会自动更新。
- 若要看某一次真实调用的最终 prompt，还需要从任务记录或用量记录中抓取运行时拼接后的 prompt。
