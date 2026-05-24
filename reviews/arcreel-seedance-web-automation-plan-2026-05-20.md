# ArcReel Seedance 网页自动化接入方案记录（2026-05-20）

## 背景

当前想法不是把 Seedance 当成新的 AI 工作流本体，而是把它作为一个“网页执行后端”接到 ArcReel 现有生成链路后面。

ArcReel 负责：

- 决定生成什么
- 组织 prompt、参考图、时长、分辨率、模式
- 走现有任务队列、版本管理、项目落盘

Seedance 网页自动化层负责：

- 登录网页
- 填 prompt
- 上传参考图
- 点击生成
- 轮询结果
- 下载成品

## 核心判断

这块更适合做成独立适配层，而不是塞进 `custom_provider`。

原因：

- `custom_provider` 假设的是“有 API endpoint”
- Seedance 这里是“浏览器驱动型 provider”
- 浏览器自动化和现有 `ImageBackend` / `VideoBackend` 协议更像一层替代后端，而不是业务逻辑的一部分

## 建议架构

### 1. 新增 Seedance Browser Client

职责只做网页层细节：

- 登录
- 保持登录态
- 上传文件
- 触发生成
- 轮询状态
- 下载结果

页面选择器、按钮文本、表单结构都集中在这一层，避免散落在业务代码里。

### 2. 再包一层 backend

建议拆成两个后端：

- `SeedanceWebImageBackend`
- `SeedanceWebVideoBackend`

它们分别实现现有的 `ImageBackend` / `VideoBackend` 协议，这样：

- `MediaGenerator` 不用改结构
- `generation_tasks.py` 不用知道网页细节
- 版本管理继续沿用现有逻辑

### 3. 任务链路保持不变

推荐链路：

`ArcReel 任务 -> backend 选择 -> Seedance Browser Client -> 网页生成 -> 下载本地文件 -> ArcReel 落盘`

这样 ArcReel 仍然是调度中心，Seedance 只是执行端。

## 登录态方案

建议主方案使用持久化 profile：

```python
await browser_type.launch_persistent_context(
    user_data_dir="/path/to/seedance-profile",
    headless=False,
)
```

特点：

- 第一次手动登录一次
- 后续自动复用 cookie、localStorage、缓存等
- 更适合这种网页型工具

`storage_state` 可以作为补充备份：

```python
await context.storage_state(path="seedance_state.json")
context = await browser.new_context(storage_state="seedance_state.json")
```

特点：

- 更轻量
- 适合测试或恢复登录态
- 但通常不如 persistent profile 完整

## 运行约束

- 同一账号要串行，避免多个生成任务抢同一个页面上下文
- 登录失效、页面改版、额度不足、生成超时、下载失败要分别区分
- 参考图和上传文件都应先落本地临时文件，再交给 Playwright 上传

## 当前结论

- Seedance 接入应当做成“网页自动化后端”
- ArcReel 继续负责编排，不直接操控网页
- 主方案用 persistent profile，`storage_state` 做辅助
- 先把图片 / 视频两条链路的适配边界定清，再落实现

## 2026-05-22 实现记录：小云雀 Web Provider

本次实际接入的平台改为小云雀（`https://xyq.jianying.com/`），provider id 为 `xyq-web`。

### 新增后端

- `lib/web_automation/xyq.py`
  - 封装 Playwright persistent profile、页面跳转、模型选择、比例选择、上传素材、`@` 引用、点击生成、等待下载。
  - 默认 profile：`~/.arcreel-browser-profiles/xyq`。
  - 默认下载目录：`~/downbyxyq`。
  - 全局串行锁：同一进程内所有小云雀任务串行执行，避免多个任务抢同一浏览器 profile。
  - 上传参考素材前复制到临时目录并重命名，避免多个 `full_body.png` 在小云雀 `@` 菜单重名。

- `lib/image_backends/xyq_web.py`
  - 实现 `ImageBackend`。
  - 支持文生图和图生图。
  - 生图 prompt 自动追加“只生成一张图。”，避免网页默认出四张。

- `lib/video_backends/xyq_web.py`
  - 实现 `VideoBackend`。
  - 支持文生视频、首帧/首尾帧、参考生视频。
  - 参考图数量上限按 7 张处理。

### Provider 注册

- `lib/providers.py` 新增 `PROVIDER_XYQ_WEB = "xyq-web"`。
- `lib/config/registry.py` 新增预置 provider：
  - 图片模型：`xyq-web/seedream-4.0-aesthetic`
  - 视频模型：`xyq-web/seedance-2.0`
  - 视频模型：`xyq-web/seedance-2.0-fast`
- `lib/image_backends/__init__.py` / `lib/video_backends/__init__.py` 注册对应 backend。
- `server/services/generation_tasks.py` 接入 provider id 到 backend factory，并传入 `profile_dir` / `download_dir` / `headless` / `timeout_seconds` 配置。
- `lib/reference_video/limits.py` 加入 `xyq-web: 7`。
- `server/services/resolution_resolver.py` 加入 `xyq-web` 默认 `720p`。
- `lib/generation_worker.py` 对 `xyq-web` 强制图片/视频并发各 1，避免网页自动化并发互抢。

### 前端配置入口

- 设置页 provider 列表会出现“小云雀 Web”。
- 小云雀不需要 API Key，但仍沿用现有“active credential 才算 ready”的机制：
  - 前端对 `xyq-web` 特判，添加凭证时只需要填名称，不要求 API Key。
  - 这条凭证的作用是启用 provider。
- 高级配置字段：
  - `profile_dir`
  - `download_dir`
  - `headless`
  - `timeout_seconds`
- `server/routers/system_config.py` 现在会把所有预置 provider 名称写入 `provider_names`，避免项目设置模型下拉里显示裸 id。

### 运行前置条件

- 需要 Python 依赖 `playwright>=1.57.0`，已写入 `pyproject.toml`。
- 需要安装 Chromium：

```bash
uv sync
uv run playwright install chromium
```

- 需要先用同一个 profile 手动登录小云雀：

```bash
playwright codegen \
  --browser=chromium \
  --user-data-dir ~/.arcreel-browser-profiles/xyq \
  https://xyq.jianying.com/
```

登录完成后不需要录登录脚本；后端会复用该 profile 的登录态。

### 当前限制

- 页面选择器来自 2026-05-22 的录制脚本，网页改版后可能需要调整 `lib/web_automation/xyq.py`。
- 连接测试目前只检查 Python Playwright 依赖和 profile 目录，不主动打开网页验证登录态，避免触发验证码或风控。
- 小云雀网页消费不走 API usage 回传，ArcReel 费用统计中 `xyq-web` 暂记为 `0 CNY`，实际费用以小云雀账户为准。
- 本实现不处理登录、滑块验证、充值、额度不足弹窗；这些仍需要人工维护。

## 2026-05-22 追加：Seedance 2.0 Fast 选择

- 前端模型列表现在会显示 `xyq-web/seedance-2.0-fast`。
- 后端 `lib/web_automation/xyq.py` 会根据传入 model id 选择小云雀网页模型：
  - `seedance-2.0`：点击普通 `Seedance 2.0`。
  - `seedance-2.0-fast`：点击录制脚本中的 `Seedance 2.0 Fast更快更便宜，经典基础版本，音视文图均可参考`。
- 普通版匹配改为排除 `Seedance 2.0 Fast` 的正则，避免页面菜单里两个模型同时包含 `Seedance 2.0` 时误点 Fast。
- 当前图片模型仍只注册 `seedream-4.0-aesthetic`；后续如果要切换 Seedream 其他版本，需要补充对应网页菜单录制片段。

## 2026-05-22 追加：参考图上传修复

- 三视图生成会默认使用全身图作为参考图，因此会走小云雀“上传参考素材”路径；文生全身图不上传参考图，不会触发该路径。
- 旧实现先点击“本地上传”，浏览器会真的弹出系统文件选择器，Playwright 后续 `set_input_files` 无法稳定接管，导致任务卡住；用户手动取消后再次生成也容易因为页面状态残留而失败。
- `lib/web_automation/xyq.py` 已改为 `page.expect_file_chooser()` 捕获文件选择器，再用 `file_chooser.set_files()` 直接写入待上传文件，避免系统文件选择器阻塞自动化流程。

## 2026-05-22 追加：三视图上传与缩略图下载修复

- 根据录制脚本，图片图生图模式只需要“上传参考素材 + 填写 prompt”，不需要在文本里额外 `@` 引用素材；`@` 主要用于多参考人物/素材的提示词绑定。三视图生成现改为上传全身图后直接填写三视图 prompt，避免 `@` 素菜单选择失败导致导入失败。
- 上传参考素材后会等待上传文件名出现在素材列表/菜单中，再继续填写 prompt，降低上传未完成就生成的概率。
- 发现小云雀图片下载可能点到缩略图按钮，实际落盘为 `480x270` JPEG。图片下载现改为：
  - 生成前记录已有图片数量；
  - 生成后等待新图片结果出现；
  - 点击新图片打开预览层后再下载；
  - 如果下载结果长边低于 700px，判定为缩略图并拒绝保存，最多尝试其他下载按钮 3 次。

## 2026-05-22 追加：`@` 引用素材选择修复

- 图生图继续不使用 `@`；参考生视频仍使用 `@`，因为视频 prompt 需要把多张角色/素材图绑定到具体文本描述。
- `@` 菜单打开流程改为：
  - 先在 `.tiptap` 末尾输入换行和 `@`；
  - 等待素材候选按钮出现；
  - 若候选未出现，再点击 `@引用角色与素材` 按钮兜底。
- 素材选择不再按上传顺序盲点，必须按上传前重命名后的唯一文件名匹配，例如 `01_...full_body.png`。匹配不到时直接报错，并把当前 `@` 菜单候选文本写入错误信息，方便定位是“上传未完成 / 菜单未刷新 / 文件名显示规则变化”。

## 2026-05-23 追加：导入预设误触与缩略图下载修复

- 三视图图生图仍可能失败并提示“导入预设失败，请检查文件格式”。根因是小云雀页面同时有“上传参考素材”和“导入预设”的上传入口，旧逻辑可能按最后一个 file input 或错误的“本地上传”按钮上传图片，导致图片被当成预设文件导入。
- `lib/web_automation/xyq.py` 现改为：
  - 上传前给“本地上传”按钮按附近文本排序；
  - 跳过离按钮/input 最近区域包含“导入预设 / 预设文件”的上传入口；
  - 优先使用声明 `accept` 为图片格式的 file chooser 或 file input；
  - 如果入口没有声明 `accept`，必须位于“参考 / 素材 / 图片 / 角色与素材”相关区域才会使用。
- 全身图下载仍可能拿到 `480x270` 缩略图。图片下载现进一步收紧为：
  - 先只在图片预览层、弹窗、viewer 区域内找“下载”按钮；
  - 若预览层按钮无法得到高清图，尝试直接读取当前可见最大预览图的 `src` 并用登录态 fetch 保存；
  - 最后才有限回退到全页面下载按钮，并继续拒绝长边低于 700px 的结果；
  - 错误信息会带最后图片尺寸和尝试按钮数，便于继续定位页面选择器变化。

## 2026-05-23 追加：按重新录制结果修正下载与上传后续流程

- 重新录制的全身图 / 三视图下载脚本显示，小云雀真实下载路径是：
  - 点击结果卡片；
  - 点击 `page.get_by_role("img", name="image")` 打开图片；
  - 直接点击全页面 `page.get_by_role("button", name="下载")`。
- 因此图片下载逻辑调整为：
  - 生成后先尝试打开新生成图片；如果没有拿到下载按钮，再尝试最后一张和第一张图片；
  - 下载时先全局等待并点击可见的“下载”按钮，之后才使用预览层 / 直接读取预览图 `src` / 全页面兜底。
- 三视图上传后卡住的问题，原因可能是上传文件在小云雀素材列表中的显示名与本地 staged 文件名不完全一致，导致等待确认文件名时阻塞。现在上传确认缩短为 5 秒，确认不到只写 warning，并按 `Escape` 尝试关闭上传面板后继续填写 prompt 和点击生成。

## 2026-05-24 追加：图片预览加载稳定等待

- `img name="image"` 数量增加只说明结果图片节点已出现在页面中，不代表预览图或高清下载资源已加载完成。过早点击下载可能导致下载中断或下载到缩略图。
- 图片下载流程现改为：打开图片并等待“下载”按钮出现后，固定等待 5 秒，再点击下载。
- 之前偶尔会连续点多次下载，是因为低清拒绝后的兜底逻辑会从“全局 / 预览层 / body”多个范围收集下载按钮，而这些范围可能指向同一个按钮。现在按按钮位置去重，尽量避免重复点击同一个下载入口。

## 2026-05-24 追加：下载前确认高清预览图

- 继续复现 `480x270` 结果，说明“下载”按钮可能属于缩略图/卡片入口，不一定是高清预览入口；单纯等待 5 秒不足以保证下载源正确。
- 图片下载流程进一步改为：
  - 点击候选图片后，必须等页面可见图片中出现长边大于等于 700px 的预览图，才认为已进入高清预览状态；
  - 如果当前候选图片没有打开高清预览，按 `Escape` 关闭后尝试其他候选图片；
  - 下载前再次检查高清预览图，确认不到则拒绝点击下载按钮，并在错误中输出当前可见图片尺寸列表；
  - 优先尝试直接保存最大预览图 `src`，如果仍不合格才尝试按钮下载。

## 2026-05-24 追加：视频长队列轮询下载

- 小云雀图片通常一分钟内完成，但视频白天可能排队 20 分钟以上，继续在生成页等待“下载”按钮会长时间占用浏览器页面并容易超时。
- 视频生成流程现拆成两步：
  - 提交任务后记录提交时间，优先从页面正文读取类似 `/5/24 14:39:31` 的任务时间；如果页面未及时显示，则使用本地提交时间兜底。
  - 下载阶段每 10 分钟进入首页历史列表，点击“全部”，按历史列表中的时间文本（例如 `-24 14:39:31`）打开对应对话；如果对话页出现“下载”按钮，则触发下载并保存到任务输出路径。
- 视频轮询期间不一直持有小云雀浏览器 profile 锁；只有提交任务和每次检查历史列表时短暂占用 profile。这样长视频排队期间，图片任务仍有机会使用同一登录态执行。
- 总等待上限仍使用 provider 高级配置里的 `timeout_seconds`，默认 2700 秒。超过后报错会包含提交时间，方便人工在小云雀历史记录里追查对应任务。
