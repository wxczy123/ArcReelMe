# AI 小说转动画工作流软件设计草案

日期：2026-05-17

## 结论

不建议继续在 ArcReel 主干上直接改造。ArcReel 可以作为参考项目，用来借鉴任务队列、供应商配置、素材版本管理、成本统计、导出思路等工程实现，但不适合作为目标产品的直接底座。

原因：

1. 现有数据结构、Agent Runtime、Skill、Prompt Builder、生成模式已经耦合较深。
2. 当前流程更像“AI 调工具”，不是面向小说动画生产的可控工作台。
3. 生图、生视频质量问题来自流程设计，不只是单个模型或单个 prompt 的问题。
4. 继续在旧逻辑上补洞，会让产品设计被历史结构牵制。

新的方向应该是：从零设计一个以“可控内容生产”为核心的软件，ArcReel 只作为参考。

## 产品目标

目标产品不是“一句话自动出片”的玩具，而是一个面向小说改编动画/短剧的 AI 工作流软件。

核心价值：

1. 让 AI 帮用户把小说拆解成可生产的视频项目。
2. 每一步都生成可读、可编辑、可回滚的中间文件。
3. 用户能控制角色、场景、剧本、分镜、提示词、视频生成质量。
4. 系统记录每次模型调用的输入、最终 prompt、输出、成本和版本。
5. 先做小样片验证，再批量生产，避免一上来大量烧钱。

## 第一版不做什么

第一版必须克制，避免一开始做成不可控大系统。

暂不做：

1. 不做“一键全书自动成片”。
2. 不做复杂多 Agent Runtime 抽象。
3. 不做 OpenAI Agents SDK / Claude SDK 双 Runtime。
4. 不做完整音频 lip-sync。
5. 不做大型素材市场。
6. 不做复杂 UI 大屏。
7. 不做自动发布。

第一版只做一条高质量小闭环：

```text
导入小说
-> 生成项目圣经
-> 生成第一集短剧脚本
-> 人工审核/编辑
-> 生成导演分镜
-> 人工审核/编辑
-> 生成角色主参考图
-> 生成 2-3 个样片镜头
-> 记录结果并支持返工
```

## 核心工作流

### 1. 导入小说

输入：

```text
txt / docx / epub / pdf
```

第一版优先支持 `txt`，其他格式后续补。

系统处理：

1. 保存原文。
2. 识别章节。
3. 建立段落索引。
4. 记录每段文本的位置。

输出：

```text
source/novel.txt
source/chapters.json
source/paragraph_index.json
```

### 2. 项目圣经

项目圣经是整个项目的一致性来源，所有后续剧本、分镜、角色图、视频 prompt 都要引用它。

输出文件：

```text
bible/story_bible.json
```

建议结构：

```json
{
  "logline": "一句话故事钩子",
  "genre": "都市情感 / 玄幻复仇 / 悬疑短剧",
  "target_platform": "竖屏短视频",
  "audience_hook": ["重逢", "误会", "反转"],
  "world": {
    "era": "现代都市",
    "rules": ["现实主义基调", "无超自然元素"],
    "tone": "冷感、压抑、暧昧"
  },
  "characters": [],
  "relationships": [],
  "visual_bible": {
    "style": "半写实韩系网络漫画风",
    "color_palette": "冷灰、暗蓝、柔和肤色",
    "camera_language": "近景表现情绪，慢推镜头制造压迫",
    "avoid": ["多头", "多人脸混合", "文字水印", "现代物件错乱"]
  }
}
```

### 3. 分集策划

不要直接把小说按字数硬切。先做分集规划。

输出文件：

```text
episodes/ep001/episode_plan.json
```

内容包括：

1. 本集原文范围。
2. 本集剧情目标。
3. 开场钩子。
4. 主要冲突。
5. 情绪曲线。
6. 结尾悬念。
7. 预计时长。
8. 推荐镜头数量。

### 4. 短剧脚本

短剧脚本是小说到分镜之间的关键层。它不是原文摘要，而是改编后的可拍摄剧本。

输出文件：

```text
episodes/ep001/episode_script.md
```

示例：

```markdown
# 第1集：破庙血影

## 本集目标
女主发现兄长还活着，并第一次意识到沈家有问题。

## 开场钩子
夜雨中，破庙里传来熟悉的咳嗽声。

## 场景 1：破庙外
- 时长：6 秒
- 画面：林晚站在雨中，盯着破庙半开的门。
- 台词：
  - 林晚：哥，是你吗？
- 情绪：恐惧中带着不敢相信。

## 场景 2：神像后
- 时长：8 秒
- 画面：雷光照亮血迹，兄长被铁链锁住。
- 台词：
  - 兄长：别信沈家。
- 结尾钩子：庙外响起沈家马车铃声。
```

### 5. 导演分镜

导演分镜不是简单 image_prompt / video_prompt，而是每个镜头的完整导演意图。

输出文件：

```text
episodes/ep001/director_storyboard.json
```

建议结构：

```json
{
  "shot_id": "E001S003",
  "duration": 6,
  "story_function": "揭示兄长还活着，制造沈家阴谋悬念",
  "viewer_focus": "兄长嘴角的血和他说出“别信沈家”时的眼神",
  "continuity_from_previous": "上一镜林晚绕到神像后，本镜接她视线落点",
  "emotional_curve": "疑惑 -> 惊恐 -> 震动",
  "characters": ["林晚", "兄长"],
  "scene": "破庙神像后",
  "composition": {
    "shot_type": "close_up",
    "camera_motion": "slow_push_in",
    "lighting": "雷光从破庙窗缝打入，照亮半张脸",
    "ambiance": "雨声、灰尘、神像阴影压迫"
  },
  "action": "兄长缓慢抬头，嘴唇颤抖，血从嘴角滑落",
  "dialogue": [
    {
      "speaker": "兄长",
      "text": "别信沈家。",
      "start": 1.2,
      "end": 3.0,
      "emotion": "虚弱、急促"
    }
  ]
}
```

### 6. 角色资料包

角色不能只是一张图。第一版至少要有结构化资料包。

目录：

```text
assets/characters/{character_id}/
  profile.json
  main_reference.png
  prompt.final.txt
  generations/
```

`profile.json` 示例：

```json
{
  "name": "苏洄",
  "role": "主角",
  "age": "二十多岁",
  "face": "肤色苍白，眼睛湿润，面部精致脆弱",
  "hair": "微卷短发或及肩发",
  "body": "纤细单薄",
  "costume": "宽松上衣、灰色开衫、围巾",
  "signature_features": ["苍白透明感", "金属戒指", "病态脆弱气质"],
  "forbidden_variations": ["不要多头", "不要多人", "不要女性化过度", "不要夸张二次元"],
  "voice_hint": "柔软、尾音轻微上扬、病中语速迟缓"
}
```

第一版角色图只生成“单人主参考图”，不要四格、多视图、拼贴图。

### 7. 场景资料包

目录：

```text
assets/scenes/{scene_id}/
  profile.json
  main_reference.png
  prompt.final.txt
  generations/
```

内容：

1. 空间结构。
2. 光影基调。
3. 时代/地域。
4. 可复用布景元素。
5. 禁止出现元素。

第一版场景图也不要“主图 + 细节小窗”拼贴，优先生成单张干净场景主参考图。

### 8. Prompt 生成与记录

任何模型调用都必须保存最终 prompt。

目录：

```text
shots/E001S003/
  image_prompt.inputs.json
  image_prompt.final.txt
  image.png
  video_prompt.inputs.json
  video_prompt.final.txt
  video.mp4
  model_result.json
```

这样以后生成质量差时，可以直接追溯：

1. 用了哪个模型。
2. 传了哪些参考图。
3. 最终 prompt 是什么。
4. 用了哪些参数。
5. 花了多少钱。

### 9. 小样片验证

不要一上来整集生成。

第一版必须支持：

```text
选择 2-3 个关键镜头
-> 生成角色图
-> 生成分镜图
-> 生成视频片段
-> 人工确认风格
-> 通过后再批量生成
```

小样片失败时，只返工角色资料包、场景资料包、导演分镜或 prompt，不继续浪费视频费用。

## 数据目录草案

```text
project/
  project.json

  source/
    novel.txt
    chapters.json
    paragraph_index.json

  bible/
    story_bible.json

  episodes/
    ep001/
      episode_plan.json
      episode_script.md
      director_storyboard.json
      review_report.json

  assets/
    characters/
      su-hui/
        profile.json
        main_reference.png
        prompt.final.txt
        generations/
    scenes/
      seattle-hotel-room/
        profile.json
        main_reference.png
        prompt.final.txt
        generations/
    props/
      ar-glasses/
        profile.json
        main_reference.png
        prompt.final.txt
        generations/

  shots/
    E001S001/
      image_prompt.inputs.json
      image_prompt.final.txt
      image.png
      video_prompt.inputs.json
      video_prompt.final.txt
      video.mp4
      model_result.json

  renders/
    ep001_preview.mp4
    ep001_final.mp4

  logs/
    ai_calls.jsonl
    tasks.jsonl
    cost.json
```

## AI 调用链路

第一版建议使用“一个总管 + 明确工具链”，不急着做多个长期 Agent。

```text
用户
-> 总管 AI
-> 调用明确工具
-> 生成文件
-> 用户审核
-> 下一步
```

工具建议：

1. `analyze_novel_to_bible`
2. `plan_episode`
3. `write_episode_script`
4. `build_director_storyboard`
5. `generate_character_reference`
6. `generate_scene_reference`
7. `build_image_prompt`
8. `generate_image`
9. `build_video_prompt`
10. `generate_video`
11. `review_quality`

## 质量控制原则

### 1. Prompt 不允许隐藏

每次模型调用必须保存最终 prompt。

### 2. 参考图必须干净

不要把四格图、多视图图、拼贴图直接喂给分镜和视频模型。

### 3. 每阶段必须可审查

用户应能看到：

1. 项目圣经。
2. 分集计划。
3. 短剧脚本。
4. 导演分镜。
5. 最终 prompt。
6. 生成结果。

### 4. 先小样片，后批量

先验证风格、角色、镜头语言，再批量生成。

### 5. 角色一致性优先于单张美图

角色参考图必须服务后续镜头复用，而不是只追求单张漂亮图。

## 技术架构建议

### 后端

建议：

```text
FastAPI
SQLite 起步，后续 PostgreSQL
异步任务队列
文件系统保存项目资产
```

不建议第一版引入过重基础设施。

### 前端

建议：

```text
React + TypeScript
工作流步骤页
文件预览/编辑
任务状态
素材管理
```

第一版 UI 不追求酷，重点是清晰、可控、可追溯。

### 任务队列

任务类型：

```text
text_generation
image_generation
video_generation
audio_generation
render
```

每个任务必须记录：

```json
{
  "task_id": "...",
  "type": "image_generation",
  "provider": "vidu",
  "model": "viduq2",
  "input_files": [],
  "prompt_file": "shots/E001S001/image_prompt.final.txt",
  "output_files": [],
  "status": "completed",
  "cost": 0.0,
  "created_at": "...",
  "completed_at": "..."
}
```

## 可借鉴 ArcReel 的部分

可以借鉴：

1. FastAPI + React 的前后端分离。
2. 项目文件系统存储。
3. 生成任务队列。
4. 多供应商配置。
5. 版本管理。
6. 成本统计。
7. SSE 任务状态推送。
8. 剪映/ffmpeg 导出思路。

不建议直接沿用：

1. 现有 Agent Runtime 结构。
2. 现有 `project.json` / `episode_N.json`。
3. 四格角色图 prompt。
4. 现有 prompt builder。
5. 现有三种 generation mode 的产品结构。
6. 现有 UI 信息架构。

## MVP 阶段计划

### MVP 0：命令行原型

目标：验证核心数据结构和生成质量。

功能：

1. 导入 `novel.txt`。
2. 生成 `story_bible.json`。
3. 生成 `episode_script.md`。
4. 生成 `director_storyboard.json`。
5. 生成单个角色主参考图。
6. 生成一个镜头图。
7. 保存最终 prompt。

### MVP 1：本地 Web 工作台

目标：让用户能在浏览器中审核和编辑中间文件。

功能：

1. 项目列表。
2. 小说导入。
3. 项目圣经查看/编辑。
4. 短剧脚本查看/编辑。
5. 导演分镜查看/编辑。
6. 角色资料包查看/编辑。
7. 单镜头生成。
8. 任务状态。

### MVP 2：小样片闭环

目标：生成 2-3 个镜头视频，验证风格和流程。

功能：

1. 选择关键镜头。
2. 批量生成分镜图。
3. 批量生成视频片段。
4. 质量评审。
5. 返工。
6. 样片导出。

### MVP 3：整集生产

目标：从小样片扩展到整集。

功能：

1. 整集镜头批量生成。
2. 视频版本管理。
3. 基础字幕。
4. 简单 BGM。
5. FFmpeg 合成。

## 后续音频管线

音频不要第一版强行做复杂。

推荐路线：

1. 一期：旁白 + 字幕 + BGM。
2. 二期：角色 TTS + 对白时间轴。
3. 三期：lip-sync。

主时间轴文件：

```text
episodes/ep001/timeline.json
```

示例：

```json
{
  "shot_id": "E001S003",
  "duration": 6.0,
  "dialogue": [
    {
      "speaker": "兄长",
      "text": "别信沈家。",
      "start": 1.2,
      "end": 3.0,
      "emotion": "虚弱、急促"
    }
  ],
  "sfx": [
    {
      "name": "雷声",
      "time": 0.4
    }
  ]
}
```

音频模型不应该自己猜什么时候说话，必须由时间轴驱动。

## 当前下一步

建议下一步先不写代码，先完成三份设计文档：

1. `product-requirements.md`：产品目标、用户流程、第一版边界。
2. `data-model.md`：项目目录、核心 JSON/Markdown 文件格式。
3. `ai-pipeline.md`：每一步 AI 输入、输出、prompt 记录、质量检查。

确认这三份后，再创建新项目骨架。
