# ArcReel 改造方向现状总结

日期：2026-05-18

## 结论

停止继续开发 `czyct`，后续主线回到 `arcreel` 上改造。

原因不是“固定工作流”这个方向错误，而是当前 `czyct` 只完成了本地 Web 壳、项目目录、设置页、任务记录和 provider 预留，缺少 ArcReel 已经具备的核心生产能力：结构化输出约束、分阶段 prompt、Pydantic 校验、任务队列、素材生成链路、分镜/视频生成链路和可恢复的工作流状态。

继续在 `czyct` 上补这些能力，本质上是在重写一个 ArcReel，成本高且容易重复踩坑。

## 目前目标重新表述

目标不是彻底抛弃 Agent，也不是必须做成完全固定流程。

更准确的目标是：在 ArcReel 基础上，保留它已有的分阶段 Agent/Skill 工作流和结构化生成能力，但把工作流做得更清晰、更可控，并重点改造图像/视频生成质量。

期望产品形态：

- 小说原文导入。
- AI 分析小说，生成项目圣经、剧本、短句脚本或分镜脚本。
- 提取并维护角色、场景、物品资产。
- 支持目标风格，风格贯穿角色图、场景图、物品图、分镜图、视频生成。
- 支持角色多形态、多参考图，如日常、生病、回忆、变身，全身图、三视图、表情、服装等。
- 支持清晰工作流控制：全部生成、当前集需要、手动选择、重做、跳过。
- 第一版不做字幕、TTS、音画分离、成本统计。
- 第一版优先模型：
  - 文本：DeepSeek `deepseek-v4-flash`
  - 图像：Vidu
  - 视频：Vidu
- 优先 Windows 原生本地运行。

## `czyct` 试验结果

`czyct` 已经完成过一版 MVP1 骨架：

- FastAPI 后端。
- React/Vite 前端。
- 本地项目目录和 `app-data`。
- 设置页、资产库、项目工作流页。
- DeepSeek/Vidu provider 预留。
- Vidu 异步任务形态。
- 角色多形态资产结构雏形。

但实际试用后发现它离可用生产链差距很大，尤其是文本生成和结构化输出。

典型问题：

- `czyct/projects/我的漫剧项目111/bible/story_bible-97f13d75.json` 返回的是 markdown fenced JSON，不是可直接消费的 JSON。
- `story_bible-bac1f3bf.json` 返回的是模型追问用户补信息的自然语言，而不是系统需要的项目圣经。
- `logs/tasks.jsonl` 显示任务系统把已有文件内容直接当 prompt 发给模型，缺少“项目圣经生成”“剧本生成”“分镜生成”等专用任务 prompt。
- 系统没有做 JSON fence 清理、`json.loads`、Pydantic 校验、失败阻断、自动修复或重试。
- 图像任务曾把 `logs/tasks.jsonl` 当作图像 prompt，说明任务创建入口过于裸露，缺少业务级封装。

这说明 `czyct` 当前只是“能调用模型的任务系统”，还不是“能生产漫剧内容的工作流系统”。

## ArcReel 已有优势

ArcReel 已经有很多可以直接复用的关键能力。

### 结构化脚本生成

相关文件：

- `arcreel/lib/script_generator.py`
- `arcreel/lib/script_models.py`
- `arcreel/lib/prompt_builders_script.py`
- `arcreel/lib/text_backends/openai.py`

已有能力：

- 使用 `TextGenerationRequest(response_schema=...)` 请求结构化输出。
- `_parse_response` 会清理 ```json fence。
- 使用 `json.loads` 解析。
- 使用 Pydantic 模型校验 `NarrationEpisodeScript`、`DramaEpisodeScript`、`ReferenceVideoScript`。
- 自动补充 episode、metadata、duration 等运行时字段。
- OpenAI-compatible 文本 backend 支持 `response_format: json_schema`。
- 如果兼容代理忽略 structured output，会检测非 JSON 并降级到 Instructor 路径。

这些正是 `czyct` 缺失的核心部分。

### 分阶段工作流

相关文件：

- `arcreel/agent_runtime_profile/.claude/skills/manga-workflow/SKILL.md`

ArcReel 的 workflow 已经把小说转视频拆成较清晰的阶段：

1. 项目设置。
2. 全局角色/场景/道具提取。
3. 分集规划。
4. 单集预处理。
5. JSON 脚本生成。
6. 资产设计。
7. 分镜图或宫格图生成。
8. 视频生成。

这套 Agent/Skill 并不是完全不能用。它的问题主要是对用户不够透明、对生成质量控制不够强，不是架构本身完全错误。

### Vidu 后端已经存在

相关文件：

- `arcreel/lib/image_backends/vidu.py`
- `arcreel/lib/video_backends/vidu.py`
- `arcreel/lib/vidu_shared.py`
- `arcreel/lib/config/registry.py`

已有能力：

- Vidu 图像：`/reference2image`。
- Vidu 视频：`/text2video`、`/img2video`、`/start-end2video`、`/reference2video`。
- 支持异步创建任务、轮询 `GET /tasks/{id}/creations`、下载结果。
- 有模型、时长、分辨率、参考图数量等基础约束。

所以后续不是从 0 接 Vidu，而是调整默认配置、补 UI 暴露、修提示词和参考图链路。

### 资产生成链路已有基础

相关文件：

- `arcreel/lib/prompt_builders.py`
- `arcreel/server/services/generation_tasks.py`
- `arcreel/agent_runtime_profile/.claude/skills/generate-assets/scripts/generate_asset.py`

已有能力：

- 角色、场景、物品有统一资产生成任务。
- 资产生成走队列。
- 资产图生成后能回写 `project.json`。
- prompt builder 会把项目风格拼进资产 prompt。

但这部分需要重点改，因为当前角色图/场景图/物品图 prompt 比较通用，不能满足稳定漫剧生产。

## ArcReel 当前主要缺口

### 1. 生图质量和一致性不够

这是当前最大问题。

需要区分不同图像任务：

- 风格参考图。
- 角色设定图。
- 角色某一形态图。
- 角色全身图。
- 角色三视图。
- 表情/服装/道具细节图。
- 场景主图。
- 场景布局图。
- 物品三视图。
- 分镜首帧图。
- 视频首帧或参考图。

不能所有任务都用同一套“资产设计图 prompt”。

### 2. 角色资产模型太薄

当前 ArcReel 角色更接近单 `character_sheet`，不满足：

- 一个角色多种形态。
- 每个形态多张参考图。
- 不同参考图槽位有明确用途。
- 项目内资产和全局资产库之间复制/复用。

需要扩展角色资产结构，例如：

- `forms.daily`
- `forms.sick`
- `forms.memory`
- `forms.transformed`
- 每个 form 下有 `main`、`full_body`、`turnaround`、`expressions`、`costume` 等引用。

### 3. 工作流 UI 需要更明确

用户需要看到“现在在哪一步、下一步是什么、可以生成哪些项、生成结果是否合格”。

建议把 ArcReel 的 Agent 工作流包装成可视化阶段：

- 小说导入
- 项目圣经
- 分集规划
- 单集剧本
- 角色/场景/物品资料包
- 分镜图
- 视频片段
- 导出

每一步都提供：

- 全部生成
- 当前集用到的部分
- 手动选择
- 重做
- 跳过
- 查看 prompt
- 查看原始返回
- 查看结构化校验结果

## 建议改造路线

### 阶段 1：改资产模型和资产库

目标：支持可复用资产，尤其是角色多形态。

任务：

- 扩展角色结构：多 form、多 reference slot。
- 场景/物品也扩展结构化 reference slot。
- 项目资产可发布到全局资产库。

### 阶段 2：重写图像 prompt 和 Vidu 参考图策略

目标：解决 ArcReel 当前生图差的问题。

任务：

- 拆分 prompt builder：
  - style prompt
  - character reference prompt
  - character form prompt
  - scene reference prompt
  - prop reference prompt
  - storyboard first-frame prompt
  - video prompt
- Vidu `reference2image` 使用合适参考图，不只是简单文本生图。
- 分镜图生成时注入角色形态、场景、物品参考图。
- 明确哪些图用于视频首帧，哪些图只用于设定。

### 阶段 3：让 Agent 工作流变得可控

让 Agent 的每一步都可见、可选择、可中断、可重做。

任务：

- 保留 Skill 编排。
- 增加阶段状态页。
- 用户可以选择继续、重做、跳过、只生成指定项。
- 重要中间文件都能在 UI 查看和编辑。

## 暂时搁置的内容

第一版不做：

- 云端部署。
- 完整开放式 Agent Runtime 重构。
- 从 0 重写 ArcReel 的工作流核心。

## 对 `czyct` 的处理建议

`czyct` 暂时保留，不继续作为主线。

不建议继续投入：

- 不要继续补完整工作流。
- 不要继续扩它的 provider 系统。
- 不要继续围绕它设计生产数据模型。

## 下一步建议

下一步直接在 `arcreel` 上做一次改造计划，建议文件可以命名为：

- `arcreel/reviews/arcreel-manjv-refactor-plan-2026-05-18.md`

计划应包含：

- Windows 原生启动验证。
- DeepSeek 文本模型接入方式。
- Vidu 图像/视频默认配置。
- 项目圣经和剧本结构化输出修复。
- 角色多形态资产模型。
- 图像 prompt 重构。
- 工作流 UI 改造。

优先做最小闭环：

1. 导入一章小说。
2. 生成合法项目圣经 JSON。
3. 生成合法单集脚本 JSON。
4. 手动或自动创建一个角色多形态参考图。
5. 用 Vidu 生成一张合格首帧图。
6. 用这张首帧图生成一个短视频片段。

只要这个闭环质量可接受，再继续扩完整项目流程。
