# ArcReel 工作流优化讨论记录（2026-05-19）

## 背景

测试项目：`/home/czy/pindou/projects/3-5987f6c8`

当前判断：

- ArcReel 的 Agent 工作流模式是可取的，整体流程可以继续沿用。
- 主要问题不在“是否使用 Agent”，而在小说信息进入图像/视频模型之前，中间层太粗，导致角色资产、分镜 prompt、资产 prompt 不够可控。
- 当前优先目标不是重写系统，而是优化“小说信息 -> 可控视觉资产 -> 高质量分镜”的链路。

本次讨论只做方案评估，尚未修改代码。

## 1. 阶段 1：全局角色 / 场景 / 道具提取

当前流程：

- 导入小说后，阶段 1 从小说中提取角色、场景、道具定义，写入 `project.json`。
- 角色提取由 `analyze-assets` subagent 完成。

当前问题：

- 角色描述太像“忠实摘录原文”，不够像“给图像模型使用的视觉设定”。
- 基础视觉信息不足，例如性别、年龄段、身高、体型、发型、脸型、五官等。
- 一些原著式、文学化、极端化描述会误导图像模型，例如：
  - “肤色苍白如纸”
  - “苍白病态”
  - “唇微抿时带血色”
- 一些非常驻、偶发细节不应进入默认形态，例如：
  - “有时佩戴粉色药片形舌钉”

优化方向：

- 将角色提取规则从“尊重原著全文描述”改成“提炼可生成、可复用、稳定的视觉设定”。
- `description` 应包含跨形态稳定信息：
  - 性别
  - 年龄段
  - 身高/体型
  - 发型/发色
  - 脸型/五官
  - 稳定标志物
  - 整体气质
- `forms.*.description` 只写该形态下的服装、状态、明显视觉变化。
- 默认形态只保留常驻形象。
- 特殊形态只提取视觉差异明显且会进入分镜的形态，例如大学时期、宴会造型、病弱状态、回忆时期等。
- 非常驻细节可以放入特殊形态或道具，不应污染默认形态。

## 2. 阶段 2：分集规划

当前流程：

- 阶段 2 将小说切分为 `source/episode_N.txt`。
- 现在主要按目标字数和附近断点切分。

当前问题：

- 按字数切分太机械，容易把一集拆成“原文片段”，而不是“短剧单集”。
- 这一步缺少“本集讲什么”的规划。

建议增加中间文件：

- 小说全文或剩余原文先生成“剧集规划中间文件”。
- 再根据剧集规划切出 `source/episode_N.txt`。

建议文件：

- `drafts/episode_plan.md`
- 或 `source/episode_plan.json`

建议内容示例：

```text
第 1 集：梦魇重逢
开头钩子：苏洄在酒店房间崩溃，宁一宵突然出现
核心冲突：六年后重逢，宁一宵发现苏洄状态异常
结尾钩子：苏洄认出宁一宵，却表现出逃避/崩溃
覆盖原文范围：从 xxx 到 xxx
主要角色：苏洄 default/depressive，宁一宵 default
主要场景：西雅图酒店
预计时长：60-90 秒
```

关键原则：

- 先按短剧结构规划一集，再按剧情锚点切小说。
- 不应只按字数切。

## 3. 阶段 3：规范化 Markdown 剧本

当前输出：

```text
场景 ID | 场景描述 | 时长 | 场景类型 | segment_break
```

当前问题：

- 信息太薄，只是简单场景表。
- 后续 JSON 剧本生成缺少更明确的剧情功能、情绪变化、角色状态等指导。

优化判断：

- 阶段 3 不应该变成完整 JSON 的重复版。
- 但可以增加少量“编剧级中间信息”，作为阶段 4 的骨架。

建议扩展为：

```text
场景 ID | 剧情功能 | 场景描述 | 出场角色 | 情绪变化 | 关键动作/对白 | 时长 | 场景类型 | segment_break
```

字段作用：

- `剧情功能`：钩子、铺垫、转折、冲突、情绪爆点、结尾钩子等。
- `出场角色`：帮助阶段 4 更稳定填 `characters_in_scene`。
- `情绪变化`：帮助阶段 4 生成更好的动作、表情、镜头语言。
- `关键动作/对白`：保留本场最重要的戏剧点。

避免重复：

- 阶段 3 不生成完整 `image_prompt` / `video_prompt`。
- 阶段 4 再生成正式 JSON、分镜图 prompt、视频 prompt、对白和角色形态。

## 4. 阶段 4：JSON 剧本生成

当前判断：

- 阶段 4 当前整体可用，问题主要来自阶段 3 输入太薄。
- Schema 本身可以暂时保留。

可优化点：

- `image_prompt.scene` 更像导演描述：
  - 人物位置
  - 景别
  - 动作
  - 表情
  - 环境关系
- `video_prompt.action` 避免泛泛而谈，要写成具体动作节奏。
- `character_forms` 应更严格继承阶段 3 的角色状态，不要自由猜。
- 如果阶段 3 增加“出场角色/情绪变化/关键动作”，阶段 4 prompt 应明确要求吸收这些字段。

### 参考生视频模式：阶段 3 / 阶段 4 补充

前提：

- 上面的阶段 3 / 阶段 4 主要针对“剧集模式 + 图生视频”。
- 如果是“剧集模式 + 参考生视频”，阶段 3 / 阶段 4 的目标会明显不同。
- 参考生视频不生成分镜图，不需要 `image_prompt`，也不走“分镜图 -> 图生视频”的链路。

两种模式的核心区别：

```text
图生视频：
source/episode_N.txt
  -> drafts/episode_N/step1_normalized_script.md
  -> scripts/episode_N.json / scenes[]
  -> 分镜图
  -> 图生视频

参考生视频：
source/episode_N.txt
  -> drafts/episode_N/step0_episode_adaptation.md
  -> drafts/episode_N/step1_reference_units.md
  -> scripts/episode_N.json / video_units[]
  -> 直接使用角色 / 场景 / 道具参考图生成视频
```

#### 参考生视频阶段 3A：单集短剧改编规划

当前新增职责：

- 由 `adapt-reference-video-episode` 先把本集小说改编为短剧结构规划。
- 输出中间文件：

```text
drafts/episode_N/step0_episode_adaptation.md
```

主要解决的问题：

- 原先直接从小说拆 `video_unit`，容易把小说段落原样摊开，导致 10-15 秒过去只有“醒来、环顾、闭眼回忆”等低密度内容。
- 小说里的“记忆涌入”“经脉疏通”“气息凝实”“现代灵魂冷静下来”等抽象内容，如果直接进入 shot text，视频模型难以执行，观众也看不到剧情信息。
- 参考生视频需要先确定短剧观看节奏，再进入具体 video_unit 和 shot 文本。

阶段 3A 输出内容：

- 本集一句话。
- 开场钩子：3-8 秒内让观众知道发生了大事。
- 结尾钩子：下一集悬念或冲突升级。
- 必须交代的信息。
- 压缩 / 不拍的信息。
- 资产与形态缺口。
- Unit 规划：`unit_id | 剧情功能 | 必须出现的可见事件 | 外化方式 | 建议 references | 角色形态 | 资产缺口`。

改编要求：

- 每个 unit 必须推进剧情，至少提供新信息、冲突升级、角色行动、反转后果或下一步目标。
- 抽象信息必须外化为可见面板、对白、屏幕文字、声音提示、闪回画面、环境反应或他人反应。
- 允许在本集范围内做短暂冷开场，不必机械遵循原文顺序。
- 不输出完整 shot 文本，完整 shot 文本交给阶段 3B。

#### 参考生视频阶段 3B：video_unit 拆分

当前职责：

- 由 `split-reference-video-units` 读取 `step0_episode_adaptation.md`，将改编规划拆成多个 `video_unit`。
- 每个 `video_unit` 对应一次视频生成调用。
- 一个 `video_unit` 内可以包含 1-4 个 `shot`。
- 输出中间文件：

```text
drafts/episode_N/step1_reference_units.md
```

当前需要解决的问题：

- 不能把图生视频的“分镜拆解思路”直接搬到参考生视频。
- 不能重新从小说自由改编，应优先继承阶段 3A 的开场钩子、结尾钩子、Unit 规划和外化方式。
- 参考生视频的关键不是“每个画面怎么构图”，而是“每次视频生成调用该喂哪些参考图，以及这些参考图能否支撑当前动作”。
- `shot text` 里不应该继续写大量外貌、服装、场景色调、光影细节，因为这些信息应由参考图承担。
- 不能在 `@名称` 中引用 `project.json` 里没有注册的角色、场景、道具。
- 如果资产表为空，或当前集需要的关键资产不存在，应该先回到资产提取 / 资产生成，而不是继续生成一堆无法落地的 `@名称`。
- 每个 shot 都必须有可见剧情信息，避免只有动作姿态或情绪变化。
- 抽象过程必须外化，例如“记忆涌入”改为系统面板 / 闪回 / 角色身体反应；“修为提升”改为测灵石亮起 / 掌心灵光稳定 / 对手表情变化。

优化方向：

- `video_unit` 按“同一时间、同一地点、主体动作连续、参考图集合稳定”来切分。
- unit 顺序、剧情功能、关键可见事件继承 `step0_episode_adaptation.md`；只有模型时长、参考图数量或资产缺口冲突时才调整。
- 不为了凑满时长强行合并不连续事件；时间、地点、主体动作发生明显变化时应拆成新 unit。
- 每个 unit 的 `references` 只放真正要喂给模型的关键资产。
- `references` 数量必须受当前视频模型的 `max_reference_images` 约束。
- 每个 `shot text` 保持直接服务视频模型，不新增抽象字段，不写成复杂导演分镜。
- 每个 `shot text` 开头补一句短镜头描述，至少带上机位 / 景别 / 运镜 / 构图里的 2-3 项，例如高角度俯拍、固定镜头、远景；平移镜头从左边树林移到右边建筑；中景、前景虚化、角色 A 与角色 B 对峙。
- 人物情绪应直接融入 `shot text`，但必须写成可见表现，例如眼神躲闪、怔住后移开视线、手指短暂停顿、呼吸变慢、嘴角僵住、眼圈泛红、下意识攥紧道具。
- 避免抽象心理词堆砌，例如内心崩溃、复杂痛苦、命运感、宿命拉扯、情绪爆炸。
- `@名称` 只用于镜头里实际可见、需要参考图的角色 / 场景 / 道具；只被提及、不出镜的人物不要 `@`，避免白占 references。
- 避免抽象比喻和文学化修辞，例如“像厚重冰层压下来”“仿佛被命运拉扯”；统一改写成可见动作、表情或身体反应。
- 镜头里实际出现的角色需要从该角色已有 `forms` 中选择一个 `form_id`；没有明确特殊造型时使用 `default_form`。
- 同一个 `video_unit` 中同一角色只允许一种形态；如果一个角色需要从常服切到病弱、回忆、礼服等特殊形态，应拆成两个 unit。
- `shot text` 聚焦可见动作和空间关系，例如：

```text
固定中景，轻微推进。@苏洄 坐在 @酒店房间 床边，低头握住 @药片，手指短暂停顿后仰头吞下，眼神疲惫地看向窗外。
```

- 避免把视觉设定重新写进 `shot text`，例如：

```text
身形偏瘦、脸色苍白的苏洄坐在昏暗冷色调酒店房间里，穿着深色大衣，低头握住白色药片。
```

- 如果需要新资产，应报告给主 agent 补充资产，而不是在 `step1_reference_units.md` 里先发明未注册资产。
- 如果需要新角色形态，应报告给主 agent 补充角色 form，而不是在 `references` 里发明新 `form_id`。
- `shots 摘要` 和完整 `shot text` 要一致，避免摘要写一套、正文写另一套。

阶段 3 推荐中间信息：

```text
unit_id | shots 数 | 总时长 | references | shots 摘要

完整 shot 文本：
Shot 1 (Xs): 短镜头描述。@角色 在 @场景 中执行具体动作，并加入可见表情 / 情绪反应；只给镜头里实际可见的资产打 @。
Shot 2 (Xs): ...

references 写法：
character:角色名/form_id, scene:场景名, prop:道具名
```

#### 参考生视频阶段 4：ReferenceVideoScript 生成

当前职责：

- 将 `step1_reference_units.md` 转成正式 JSON。
- 输出 `ReferenceVideoScript.video_units[]`。
- 每个 `video_unit` 包含：
  - `unit_id`
  - `shots[]`
  - `references[]`
  - `duration_seconds`

优化方向：

- 严格继承阶段 3 的 `unit_id`、shot 数、shot 顺序、references 和时长，不要自由重排。
- `duration_seconds` 应由 `shots[].duration` 求和得到，不要手填出错。
- `shots[].duration` 必须来自当前视频模型支持的时长集合。
- `references[]` 必须覆盖 `shot text` 中出现的全部 `@名称`，不能多，也不能漏。
- `references[]` 的 `name` 必须来自 `project.json` 的 characters / scenes / props。
- 角色引用增加 `form_id`：`{"type":"character","name":"苏洄","form_id":"sick"}`；scene / prop 不写 `form_id`。
- 不生成 `image_prompt` / `video_prompt`，也不引入图生视频的分镜图字段。
- 参考生视频的“导演语言”应体现在动作连续性和人物关系上，而不是细分景别、构图、光影。
- 如果某个 unit 需要的参考图超过模型上限，应回到阶段 3 重新拆 unit，而不是在阶段 4 硬塞。

阶段 4 输出质量标准：

- 每个 `video_unit` 都能直接映射为一次可执行的视频生成任务。
- 每个 `@名称` 都能找到对应资产图。
- 每个角色 reference 都能解析到 `project.json.characters[角色].forms[form_id]`，并按该形态的 `storyboard_ref_slot` 取图。
- 每个 unit 的参考图集合足够少、足够明确，并且能支撑该 unit 的动作。
- JSON 不承担资产创造职责，只负责把阶段 3 的 unit 计划结构化。

## 5. 阶段 5：资产生成 Prompt

### 角色图 Prompt

当前问题：

- 角色 prompt 拼接太工程化。
- 当前结构类似：

```text
跨形态稳定外貌：...
当前形态：...
```

- 正向/负向防崩短语过多，例如：

```text
角色面部、发型、服装、配饰保持一致；五官对称、手指完整为五指、肢体比例协调。
画面避免：水印、多余文字、低分辨率、手指畸形、分格、多角色、裁切身体。
```

优化方向：

- 删除“跨形态稳定外貌”“当前形态”等工程化标题。
- 将基础外貌和当前形态合并成自然语言。
- 保留核心构图要求：
  - 单人全身
  - 从头到脚完整入画
  - 正面或轻微三分之二角度站姿
  - 干净浅色背景
  - 不分格
  - 不拼图
  - 不出现第二个人
  - 不要出现文字
- 删除大部分弱价值防崩短语，避免污染主体描述。

建议风格示例：

```text
角色「苏洄」单人全身设定图。
他是二十多岁的年轻男性，身形纤细，黑色柔软短发，五官精致，眼神安静敏感。
当前造型为六年后重逢时期：灰色长毛开衫、彩色格纹围巾、旧大衣和旧鞋。
整体是真人短剧质感，干净浅色背景，角色从头到脚完整入画，不要出现文字。
```

### 场景图 Prompt

当前模板：

```text
风格：画风：真人电视剧风格，精品短剧画风，大师级构图

标志性场景「西雅图酒店」的视觉参考。

现代商务酒店，灰蒙蒙的冬日天色透过落地玻璃窗，大堂冷色调灯光。2208房间内昏暗安静，有木质香薰气味，白色小行李箱倒在地毯上。冷气开得很足

主画面占四分之三区域展示环境整体外观与氛围，右下角嵌入关键细节小图。

空间透视正常，陈设固定，光影统一。

画面避免：水印、多余文字、低分辨率、手指畸形。
```

当前问题：

- “主画面四分之三 + 右下角细节小图”会把场景参考图做成版式图，不一定适合后续作为分镜参考。
- 防崩短语价值有限。
- 场景图更应该是清晰可复用的环境设定图。

后续可讨论方向：

- 场景参考图默认生成“单张完整环境图”，不要拼接小图。
- 如需要细节图，应拆成额外槽位，而不是塞进同一张图。

### 道具图 Prompt

当前模板：

```text
风格：画风：真人电视剧风格，精品短剧画风，大师级构图

道具「《网》装置艺术」的多视角展示。

由数千只白色纸折叠蝴蝶组成，蝴蝶上用细线悬挂，墙面映出完整丝线构成的"网"的光影——每只蝴蝶都被线笼罩。蓝色灯光浸透整个展区。纸上隐约有字样

三视图水平排列于纯净浅灰背景：左侧正面全视图、中间 45° 侧视图体现立体感、右侧关键细节特写。

外观结构完整，焦点清晰。

画面避免：水印、多余文字、低分辨率、手指畸形。
```

当前问题：

- 所有道具都强制三视图不一定合理。
- 大型装置艺术、花束、手稿、烟盒等道具适合不同图像结构。

后续可讨论方向：

- 普通小道具可以三视图。
- 大型装置/艺术品/花束类道具更适合单张产品图或环境中展示图。
- 可按道具类型增加 `display_mode`，但这不是第一优先级。

## 6. Seedance 网页自动化接入

需求：

- 当前使用 Vidu API 生图质量较差。
- 希望使用 Seedance，但 Seedance 只有网页版，没有 API。
- 设想用 Playwright 自动打开 Seedance 官网完成生图、生视频，并接入 ArcReel。

可行方案：

```text
ArcReel 生成任务
  -> 自定义 image/video backend
  -> Playwright Worker
  -> 打开 Seedance 网页
  -> 填写 prompt / 上传参考图
  -> 等待生成
  -> 下载结果
  -> 回写 ArcReel 文件路径和版本记录
```

建议架构：

- 不要在业务代码里散落 Playwright 调用。
- 应封装为独立 provider/backend：

```text
lib/image_backends/seedance_web.py
lib/video_backends/seedance_web.py
```

- Playwright 自动化逻辑放在独立 worker 或脚本目录：

```text
tools/seedance_web_worker/
```

主要风险：

- 网页登录态会过期，需要维护 cookie/session。
- 网页 UI 变化会导致脚本失效。
- 生图/生视频耗时长，需要支持排队、等待、断点续查。
- 下载、失败重试、并发控制需要设计。
- 可能涉及平台使用条款，需要用户自行确认。

判断：

- 技术上可以接入 ArcReel，因为 ArcReel 本身是任务队列模式。
- 但这是工程量最大的部分，建议排在 prompt 和流程优化之后。

## 建议优先级

1. 优化阶段 1 资产提取 prompt，让角色资料更干净、更适合图像模型。
2. 优化阶段 5 角色/场景/道具资产 prompt，先去掉工程化拼接和弱价值防崩短语。
3. 增强阶段 3 Markdown 中间剧本，为阶段 4 提供更好的剧情骨架。
4. 优化阶段 4 JSON 剧本 prompt，让分镜图 prompt 和视频 prompt 更像导演语言。
5. 设计阶段 2 的剧集规划中间文件，把“按字数切分”升级为“按短剧集结构切分”。
6. 最后再做 Seedance Web 自动化 provider。

## 当前不动的部分

- 暂不重写 ArcReel 架构。
- 暂不放弃 Agent 工作流。
- 暂不修改全局资产库结构。
- 暂不改视频生成流程。
- 暂不立刻接 Playwright。

## 后续可执行任务

下一步建议先做：

```text
优化 analyze-assets 提示词：
1. 增加角色基础视觉字段要求
2. 删除文学化/极端化描述
3. 默认形态只保留常驻造型
4. 特殊形态只保留视觉差异明显且会进入分镜的状态
5. 输出前自检 description 是否适合直接给图像模型
```

然后再做：

```text
优化 lib/prompt_builders.py：
1. 重写 build_character_full_body_prompt
2. 重写 build_character_three_view_prompt
3. 简化 scene/prop prompt
4. 减少弱价值负向提示词
5. 保留“不要出现文字”等关键限制
```

## 2026-05-20 阶段 2 简版优化

阶段 2 先不引入复杂的 AI 剧集规划中间文件，改为“章节识别 + 按 N 章切一集”优先，原有字数切分作为兜底。

新增脚本：

```text
agent_runtime_profile/.claude/skills/manage-project/scripts/split_by_chapters.py
```

脚本行为：

- 只识别独立单行章节标题。
- 内置常见格式：
  - `第1章`
  - `第一章`
  - `第 1 章`
  - `Chapter 1`
  - `CHAPTER 1`
  - `01`
- 标题后可以有标题文本，也可以没有标题。
- 第一个章节标题之前的内容不进入 `episode_N.txt`；正式执行时写入 `source/preface.txt`。
- 支持 `--dry-run` 展示识别结果，用户确认后再正式切分。
- 正式执行生成 `source/episode_N.txt` 和 `source/episode_index.json`。
- 默认不覆盖已有输出，需显式加 `--overwrite`。

工作流接入：

- `manga-workflow` 阶段 2 改为优先询问用户“每集几章”。
- 先运行：

```bash
python .claude/skills/manage-project/scripts/split_by_chapters.py --source {源文件} --chapters-per-episode {每集章数} --dry-run
```

- dry-run 展示识别章节数、前言字数、前 10 章 / 后 5 章、预计生成集数和每集章节范围。
- 用户确认后去掉 `--dry-run` 正式切分。
- 如果章节识别失败、结果明显不可信，或用户要求按字数切分，则回退旧的 `peek_split_point.py` + `split_episode.py`。

## 2026-05-20 阶段 5 资产 Prompt 简化

本次按“减少工程化拼接、减少泛化防崩短语”的原则简化资产图 prompt。

修改文件：

```text
lib/prompt_builders.py
tests/test_prompt_builders.py
```

实际规则：

- 风格前缀不再生成 `风格：画风：...`，如果项目 style 已经以 `画风：` 开头，则原样保留。
- 角色全身图：
  - 删除 `跨形态稳定外貌：`、`当前形态：` 等工程标签。
  - 直接合并角色基础描述和形态描述。
  - 结尾只保留：`单人全身参考图，角色从头到脚完整入画，纯白色背景，不要文字。`
  - 删除角色防崩段和 `画面避免` 尾巴。
- 角色三视图：
  - 同样删除工程标签和泛化负向尾巴。
  - 保留三视图布局说明，并补 `不要文字。`
- 场景图：
  - 删除 `主画面占四分之三区域`、`右下角嵌入关键细节小图`。
  - 删除 `空间透视正常，陈设固定，光影统一。`
  - 删除 `画面避免` 尾巴。
- 道具图：
  - 保留多视角/三视图布局和 `外观结构完整，焦点清晰。`
  - 删除 `画面避免` 尾巴。

## 2026-05-20 参考生视频角色形态与默认参考槽位

本次把参考生视频也接入角色多形态资产库，并同步修正图生视频剧本 prompt 的角色形态信息。

修改点：

- `split-reference-video-units` 阶段 3 读取角色 `forms`，要求角色 reference 写成 `character:角色名/form_id`。
- `ReferenceVideoScript.video_units[].references[]` 的 character 条目支持 `form_id`；scene / prop 仍不允许 `form_id`。
- 参考生视频执行时按 `reference.form_id -> forms[form_id].storyboard_ref_slot` 解析角色参考图。
- 如果当前槽位没有图，解析层会回退到同形态 `full_body`，避免三视图尚未生成时直接失败。
- `build_reference_video_prompt` 现在向文本模型展示每个角色的 `default_form` 和全部 forms，要求模型根据剧情选择形态。
- `build_drama_prompt` 的 `<characters>` 也改为列出 forms 详情，图生视频生成 `character_forms` 时有可选形态依据。
- 新建 / 规范化角色形态的 `storyboard_ref_slot` 默认值从 `full_body` 改为 `three_view`；这个开关同时影响图生视频分镜参考图、宫格参考图和参考生视频参考图。

涉及文件：

```text
agent_runtime_profile/.claude/agents/split-reference-video-units.md
lib/character_assets.py
lib/script_models.py
lib/prompt_builders_reference.py
lib/prompt_builders_script.py
lib/data_validator.py
server/services/reference_video_tasks.py
server/routers/reference_videos.py
server/agent_runtime/sdk_tools/enqueue_assets.py
frontend/src/components/canvas/reference/ReferencePanel.tsx
frontend/src/types/reference-video.ts
```

## 2026-05-23 参考生视频阶段 3 剧情密度优化

本次针对参考生视频模式出现的“shot 文本有镜头语言但剧情太水、抽象内容不可拍”的问题，把阶段 3 拆成两步：

- 阶段 3A：`adapt-reference-video-episode` 生成 `drafts/episode_N/step0_episode_adaptation.md`。
- 阶段 3B：`split-reference-video-units` 读取 step0 规划，再生成 `drafts/episode_N/step1_reference_units.md`。

新增规则：

- step0 必须包含本集一句话、开场钩子、结尾钩子、必须交代的信息、压缩 / 不拍的信息、资产与形态缺口、Unit 规划。
- 每个 unit 必须推进剧情，不能只写醒来、环顾、沉思、行走、表情变化。
- “记忆涌入”“经脉疏通”“气息凝实”“现代灵魂占据身体”等抽象内容必须外化为可见面板、对白、屏幕文字、声音提示、闪回画面、环境反应或他人反应。
- `split-reference-video-units` 不再直接从小说自由改编，而是优先继承 step0 的开场钩子、结尾钩子、Unit 规划和外化方式。
- Web 草稿路由新增 reference_video 的 step0 文件映射，左侧草稿列表可显示“单集改编规划”。

同时新增风格模板：

- `anim_cn_3d_realistic`
- 名称：`3D国风写实`
- Prompt：`抖音漫剧同款 3D 国风写实画风，极致精细建模，清晰呈现面部毛孔、自然油光，皮肤纹理真实细腻，衣物布料质感分明，电影级高清画质，柔和写实光影`

## 2026-05-24 资产风格分类型与手动补片入口

本次把项目风格模板从“同一段 prompt 直接给人物 / 场景 / 物品共用”，扩展为“模板可按资产类型覆盖 prompt”。旧模板没有专属配置时仍回退通用 prompt，保持原有表现。

`3D国风写实` 现在使用三段资产类型 prompt：

- 人物：保留面部毛孔、自然油光、皮肤纹理、衣物布料等人物质感描述。
- 场景：保留 3D 国风写实、精细建模、电影级高清、柔和写实光影，并明确“图中不要出现任何人物、角色”。
- 物品：保留 3D 国风写实、精细建模、电影级高清，并明确“图中不要出现任何人物、角色”。

同时确认并测试了场景、物品的直接上传资产图链路：

- `SceneCard` / `PropCard` 工具栏已有上传按钮。
- 后端 `/upload/scene`、`/upload/prop` 会把图片保存到 `scenes/`、`props/`，并写回 `scene_sheet` / `prop_sheet`。

参考生视频也新增了手动上传视频入口：

- 单元预览面板新增“上传视频”按钮，只接受 `.mp4`。
- 后端新增 `/reference-videos/episodes/{episode}/units/{unit_id}/upload`，保存到 `reference_videos/{unit_id}.mp4`。
- 上传后写入版本历史，提取缩略图，回写 `generated_assets.video_clip` / `video_thumbnail` / `status=completed`。
- 上传或生成成功都会通过 `reference_video_ready` 事件带 `asset_fingerprints` 通知前端。

修复一个参考生视频状态显示问题：

- 以前如果某个 unit 旧任务失败、后续又成功生成视频，画布可能仍按旧 failed 任务显示失败。
- 现在前端优先以 `generated_assets.video_clip` 判定 ready，不再被旧 failed 队列行覆盖。
- SSE 收到 `reference_video_ready` 后会主动重拉对应 episode 的 `video_units`，避免只刷新项目详情而参考视频 store 仍停留在旧状态。
- 列表接口增加读时自愈：如果磁盘上已经存在 `reference_videos/{unit_id}.mp4`，但剧本 JSON 还没写 `generated_assets.video_clip`，会补齐 `video_clip`、`video_thumbnail` 和 `status=completed`，避免“文件已生成但前端仍显示失败”的脏数据残留。
