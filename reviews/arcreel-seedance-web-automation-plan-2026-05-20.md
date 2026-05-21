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

