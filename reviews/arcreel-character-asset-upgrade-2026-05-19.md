# ArcReel 角色资产库多形态升级记录

日期：2026-05-19

## 目标

把角色资产从“一个角色一张 `character_sheet`”升级为“一个角色多个形态，每个形态固定两个输出槽位”：

- `full_body`：单人全身主参考图，默认喂给分镜/宫格/参考图收集。
- `three_view`：三视图，默认用于一致性审阅，也可由用户切换为分镜参考图。
- `input_refs`：用户上传的生成输入参考图，只作为生成 `full_body` / `three_view` 的输入，不作为最终角色设计图。
- `storyboard_ref_slot`：当前形态用于分镜的默认参考槽位，默认 `full_body`。

本次不做成本估算改造。旧字段 `character_sheet` / `reference_image` 不再作为真相源；但在读写边界保留了轻量迁移：旧 `character_sheet` 会转入默认形态 `full_body`，旧 `reference_image` 会转入默认形态 `input_refs`，避免旧测试和导入包直接断裂。

## 新数据结构

`project.json` 中角色结构：

```json
{
  "characters": {
    "苏洄": {
      "description": "跨形态稳定外貌：年龄、体态、五官、标志物",
      "voice_style": "...",
      "default_form": "default",
      "forms": {
        "default": {
          "label": "默认造型",
          "description": "常规服装和状态",
          "storyboard_ref_slot": "full_body",
          "input_refs": [],
          "refs": {
            "full_body": {
              "path": "characters/苏洄/default/full_body.png",
              "purpose": "storyboard_reference"
            },
            "three_view": {
              "path": "characters/苏洄/default/three_view.png",
              "purpose": "consistency_review"
            }
          }
        }
      }
    }
  }
}
```

剧本 `drama scene` 增加：

```json
{
  "characters_in_scene": ["苏洄", "宁一宵"],
  "character_forms": {
    "苏洄": "hotel_sick",
    "宁一宵": "default"
  }
}
```

## 后端改动

核心新增：

- `lib/character_assets.py`
  - 统一角色 forms/ref slot 工具。
  - 提供 `ensure_character_forms()`、`make_character_entry()`、`get_storyboard_ref_path()`、`set_ref_path()`、`character_ref_resource_id()`。
  - 固定槽位：`full_body`、`three_view`。

项目管理：

- `lib/project_manager.py`
  - 新增角色形态 CRUD：`add_character_form()`、`update_character_form()`、`delete_character_form()`、`update_character_default_form()`。
  - 新增槽位路径与输入参考图写入：`update_character_ref_path()`、`add_character_input_ref()`。
  - `get_pending_character_refs()` 按每个角色/形态/槽位扫描缺失项。
  - `collect_reference_images()` 改为按 `character_forms -> storyboard_ref_slot` 收集角色参考图。

生成任务：

- `server/services/generation_tasks.py`
  - 新增 `character_ref` 任务执行器。
  - 旧 `character` 任务兼容转发到 `default/full_body`。
  - 生成 `full_body` 时使用该形态 `input_refs`。
  - 生成 `three_view` 时优先使用同形态 `full_body`，再附带 `input_refs`。
  - 分镜/宫格参考图按当前镜头的 `character_forms` 和形态 `storyboard_ref_slot` 解析。

Prompt：

- `lib/prompt_builders.py`
  - 新增 `build_character_full_body_prompt()`。
  - 新增 `build_character_three_view_prompt()`。
  - `build_character_prompt()` 保留为全身图 wrapper。

版本与文件：

- `lib/media_generator.py`
  - 新增资源类型 `character_refs`，输出到 `characters/{角色}/{form_id}/{slot}.png`。
- `lib/version_manager.py`
  - 新增 `character_refs` 版本类型。
  - 版本路径：`versions/character_refs/{角色}/{form_id}/{slot}_vN_时间.png`。
- `server/routers/versions.py`
  - 新增带 path 参数的 `character_refs` 版本查询和还原，支持 resource_id 内含 `/`。

API：

- `server/routers/generate.py`
  - 新增：`POST /api/v1/projects/{project}/generate/character-ref/{char}/{form_id}/{slot}`。
  - 旧：`POST /api/v1/projects/{project}/generate/character/{char}` 仍可用，但会入队 `character_ref` 的 `default/full_body`。
- `server/routers/characters.py`
  - 新增形态与槽位接口：
    - `POST /projects/{project}/characters/{char}/forms`
    - `PATCH /projects/{project}/characters/{char}/forms/{form_id}`
    - `DELETE /projects/{project}/characters/{char}/forms/{form_id}`
    - `POST /projects/{project}/characters/{char}/forms/{form_id}/refs/{slot}`
    - `POST /projects/{project}/characters/{char}/forms/{form_id}/input-refs`
- `server/routers/files.py`
  - 旧上传 `character` 会写入默认形态 `full_body`。
  - 旧上传 `character_ref` 会写入默认形态 `input_refs`。

校验与状态：

- `lib/script_models.py`
  - `DramaScene` 增加 `character_forms`。
- `lib/prompt_builders_script.py`
  - 剧本生成 prompt 要求 `character_forms` 与 `characters_in_scene` 对齐，form_id 必须来自项目角色 forms。
- `lib/data_validator.py`
  - 校验角色 forms、refs、input_refs。
  - 校验 drama scene 的 `character_forms`。
- `lib/status_calculator.py`
  - 角色完成度改为：每个形态的 `full_body` 和 `three_view` 都存在才算完成。

其他服务：

- `server/services/project_cover.py`
  - 项目封面角色兜底改为默认形态的 storyboard ref。
- `server/services/project_events.py`
  - SSE snapshot 输出角色 forms。
- `server/services/reference_video_tasks.py`
  - 参考视频的角色图片解析改为默认形态 storyboard ref。

## Agent / Skill 改动

MCP 工具：

- `server/agent_runtime/sdk_tools/enqueue_assets.py`
  - `generate_assets` / `list_pending_assets` 只负责 `scene` / `prop`。
  - 新增 `list_pending_character_refs`。
  - 新增 `generate_character_refs`。
  - 支持 targets：

```json
{
  "targets": [
    {
      "character": "苏洄",
      "form_id": "hotel_sick",
      "slots": ["full_body", "three_view"]
    }
  ]
}
```

Agent profile：

- `agent_runtime_profile/.claude/agents/analyze-assets.md`
  - 要求提取默认形态和视觉差异明显、会进入分镜的特殊形态。
- `agent_runtime_profile/.claude/skills/generate-assets/SKILL.md`
  - 角色生成改为角色形态参考图生成。
- `agent_runtime_profile/.claude/skills/manga-workflow/SKILL.drama.md`
- `agent_runtime_profile/.claude/skills/manga-workflow/SKILL.narration.md`
- `agent_runtime_profile/CLAUDE.drama.md`
- `agent_runtime_profile/CLAUDE.narration.md`
  - “只生成当前剧集需要的角色”改为“只生成当前剧集实际使用的角色形态”。

## 全局资产库

数据库：

- `lib/db/models/asset.py`
  - `assets` 表新增 `forms_json`。
- `lib/db/repositories/asset_repo.py`
  - create/update 支持 `forms_json`。
- 迁移：
  - `alembic/versions/36d8f84efb2c_add_forms_json_to_assets.py`

路由：

- `server/routers/assets.py`
  - character 类型资产序列化输出 `forms`。
  - “加入资产库”会复制角色全部 forms 图片和 `input_refs` 到 `_global_assets/character/{bundle}/...`。
  - “从资产库导入”会恢复 forms 和图片目录。
  - 角色卡片预览使用默认形态的 `storyboard_ref_slot` 图片。
  - scene/prop 继续使用原 `image_path`。

## 前端改动

类型：

- `frontend/src/types/project.ts`
  - 新增 `CharacterRefSlot`、`CharacterRef`、`CharacterForm`。
- `frontend/src/types/script.ts`
  - `DramaScene` 增加 `character_forms`。
- `frontend/src/types/asset.ts`
  - 全局资产 character 增加 `forms`。

API：

- `frontend/src/api.ts`
  - 新增 `addCharacterForm()`、`updateCharacterForm()`、`deleteCharacterForm()`。
  - 新增 `uploadCharacterFormRef()`、`uploadCharacterInputRef()`。
  - 新增 `generateCharacterRef()`。

UI：

- `frontend/src/components/canvas/lorebook/CharacterCard.tsx`
  - 角色卡显示基础描述/声音风格。
  - 形态列表切换。
  - 每个形态显示 `full_body` / `three_view` 两个槽位。
  - 每个形态支持上传 `input_refs`。
  - 每个槽位支持上传、生成/重新生成、预览。
  - 每个形态可选择分镜默认参考槽位。
- `frontend/src/components/canvas/lorebook/CharactersPage.tsx`
  - 接入新增形态和槽位回调。
- `frontend/src/components/canvas/StudioCanvasRouter.tsx`
  - 角色生成 loading 改为 `character/form/slot` 粒度。
- `frontend/src/components/assets/AssetCard.tsx`
  - character 预览使用默认形态 storyboard ref。
- `frontend/src/components/canvas/reference/ReferencePanel.tsx`
  - 参考视频角色预览使用默认形态 storyboard ref。
- `frontend/src/i18n/{zh,en,vi}/dashboard.ts`
  - 补齐多形态角色 UI 文案。

## 测试更新

已更新测试覆盖：

- 角色 forms 数据结构。
- `character_ref` 生成路由和任务执行。
- Agent 工具：角色形态参考图独立于 scene/prop 资产工具。
- 分镜、宫格、参考视频收集角色参考图。
- 全局资产库 character forms 导入/导出。
- 文件上传进入默认形态 `full_body` / `input_refs`。
- 项目状态统计按两个槽位计算完成度。

验证结果：

```bash
cd frontend && pnpm check
# 74 files passed, 546 tests passed

AUTH_ENABLED=true uv run pytest
# 2755 passed, 7 warnings
```

说明：当前本机 `.env` 若设置 `AUTH_ENABLED=false`，直接运行 `uv run pytest` 会导致 auth 相关测试按关闭认证分支执行，断言会失败。验证全量测试时使用 `AUTH_ENABLED=true uv run pytest`。

## 追加变更：角色输入参考图规则（2026-05-19）

本次将 `input_refs` 的语义收窄为“全身图生成参考”，避免三视图同时参考全身图和用户输入参考图导致形象漂移。

调整后的规则：

- 生成 `full_body`：
  - 使用当前形态的 `forms[form_id].input_refs`。
  - 如果没有 `input_refs`，走纯文本生图。
- 生成 `three_view`：
  - 只使用同一形态的 `refs.full_body.path`。
  - 如果 `full_body` 不存在或文件缺失，走纯文本生图。
  - 不再读取 `input_refs`。

涉及文件：

- `server/services/generation_tasks.py`
  - 调整 `execute_character_ref_task()` 内参考图收集规则。
- `frontend/src/i18n/{zh,en,vi}/dashboard.ts`
  - 将 UI 文案从“生成输入参考图”改为“全身图生成参考”，明确它只服务于全身图生成。
- `tests/test_generation_tasks_service.py`
  - 新增回归测试，覆盖 `full_body` 使用 `input_refs`、`three_view` 只使用 `full_body`、无 `full_body` 时三视图纯文本生成。

## 追加变更：输入参考图删除与角色版本入口（2026-05-19）

本次补齐两个前端可用性缺口：

1. `input_refs` 可以删除。
2. 角色图版本历史入口从旧“单角色图”改为新结构的“角色/形态/槽位”粒度。

输入参考图删除规则：

- 删除对象是 `forms[form_id].input_refs` 中的某一张全身图生成参考。
- 前端在每张输入参考图缩略图右上角显示删除按钮。
- 删除时调用：

```text
DELETE /api/v1/projects/{project}/characters/{character}/forms/{form_id}/input-refs
body: { "path": "characters/{角色}/{form_id}/input_refs/xxx.png" }
```

- 后端会先尝试删除磁盘文件，再从 `project.json` 的 `input_refs` 数组移除路径。

角色参考图版本入口：

- 每个形态的两个槽位都显示版本入口：
  - `full_body`
  - `three_view`
- 版本资源类型为 `character_refs`。
- 版本资源 ID 为：

```text
{角色名}/{form_id}/{slot}
```

示例：

```text
Hero/default/full_body
Hero/default/three_view
```

- 前端 `VersionTimeMachine` 已支持 `character_refs`。
- `frontend/src/api.ts` 对 `character_refs` 的版本 URL 做了专门处理，保留 `resource_id` 中的 `/` 路径分段，否则会错误编码成单段路径。

涉及文件：

- `frontend/src/components/canvas/lorebook/CharacterCard.tsx`
  - 输入参考图缩略图增加删除按钮。
  - 每个角色参考图槽位增加 `VersionTimeMachine(resourceType="character_refs")`。
- `frontend/src/components/canvas/lorebook/CharactersPage.tsx`
  - 透传 `onDeleteCharacterInputRef`。
- `frontend/src/components/canvas/StudioCanvasRouter.tsx`
  - 新增 `handleDeleteCharacterInputRef()`，删除后刷新项目数据。
- `frontend/src/components/canvas/timeline/VersionTimeMachine.tsx`
  - 支持 `character_refs` 类型。
- `frontend/src/api.ts`
  - 新增/接入 `deleteCharacterInputRef()`。
  - `getVersions()` / `restoreVersion()` 支持 `character_refs` 的斜杠资源 ID。
- `frontend/src/i18n/{zh,en,vi}/dashboard.ts`
  - 新增 `delete_input_ref`。
- `tests/test_characters_router.py`
  - 覆盖删除输入参考图后同步清理 `project.json`。
- `tests/test_project_manager_more.py`
  - 覆盖 `ProjectManager.remove_character_input_ref()`。
- `frontend/src/api.test.ts`
  - 覆盖 `character_refs` 版本 URL。
- `frontend/src/components/canvas/lorebook/CharacterCard.test.tsx`
  - 覆盖输入参考图删除按钮和槽位版本入口。
- `frontend/src/components/canvas/timeline/VersionTimeMachine.test.tsx`
  - 覆盖 `character_refs` 版本资源。
- `frontend/src/components/canvas/StudioCanvasRouter.test.tsx`
  - 覆盖删除输入参考图的前端回调链。

本次验证：

```bash
pnpm --dir frontend exec tsc --noEmit --pretty false --project tsconfig.json
pnpm --dir frontend exec vitest run src/api.test.ts src/components/canvas/lorebook/CharacterCard.test.tsx src/components/canvas/timeline/VersionTimeMachine.test.tsx src/components/canvas/StudioCanvasRouter.test.tsx
uv run pytest tests/test_characters_router.py tests/test_project_manager_more.py
```

结果：

- 前端类型检查通过。
- 前端 4 个测试文件通过，49 个测试通过。
- 后端 2 个测试文件通过，33 个测试通过。
- 本环境直接运行 `uv run pytest ...` 时沙箱无法写 `~/.cache/uv`，实际验证使用提权运行同一命令。

## Bugfix：版本切换后图片仍显示旧图（2026-05-19）

问题现象：

- 在角色参考图版本面板里切换到 v2 后，后端版本状态已切换，但人物设计图仍显示 v1。

根因：

- `VersionManager.restore_version()` 之前使用 `shutil.copy2()` 把版本文件复制到当前文件。
- `copy2()` 会保留源版本文件的旧 `mtime`。
- 前端图片 URL 使用当前文件的 `mtime_ns` 作为缓存指纹，例如：

```text
/api/v1/files/{project}/characters/Alice/default/full_body.png?v={mtime_ns}
```

- 如果还原后当前文件的 `mtime_ns` 没变或变回旧值，浏览器会继续使用缓存里的旧图片，表现为“版本切换了，但图没变”。

修复：

- `lib/version_manager.py`
  - 还原版本时从 `shutil.copy2()` 改为 `shutil.copyfile()`。
  - 复制完成后用 `os.utime(..., ns=...)` 强制刷新当前文件 `mtime_ns`。
  - 确保后端返回的 `asset_fingerprints` 变化，前端图片 URL 随之变化。
- `tests/test_version_manager_more.py`
  - 新增测试：还原 `character_refs` 后当前文件内容变为目标版本，且 `mtime_ns` 前进。
- `tests/test_versions_router.py`
  - 新增测试：`character_refs` 还原返回 `characters/{角色}/{form_id}/{slot}.png` 的 fingerprint，并同步角色槽位元数据。

本次验证：

```bash
uv run ruff check lib/version_manager.py tests/test_version_manager_more.py tests/test_versions_router.py
uv run pytest tests/test_version_manager_more.py tests/test_versions_router.py
pnpm --dir frontend exec tsc --noEmit --pretty false --project tsconfig.json
pnpm --dir frontend exec vitest run src/components/canvas/timeline/VersionTimeMachine.test.tsx src/components/canvas/lorebook/CharacterCard.test.tsx src/api.test.ts
```

结果：

- Python ruff 通过。
- 版本管理/版本路由测试 13 个通过。
- 前端类型检查通过。
- 前端 3 个测试文件通过，43 个测试通过。

## Bugfix：新结构角色图缺少项目级缓存指纹（2026-05-19）

进一步复查后发现，上一个 mtime 修复只解决了“还原后文件指纹可能不变”的问题；还有一个更直接影响新结构角色图的问题：

- `compute_asset_fingerprints()` 之前只扫描媒体目录的一层子目录。
- 旧角色图路径是：

```text
characters/Alice.png
characters/refs/Alice.png
```

- 新角色图路径是：

```text
characters/Alice/default/full_body.png
characters/Alice/default/three_view.png
```

- 这是二级目录。项目刷新时后端没有把这些路径放进 `asset_fingerprints`。
- 前端拿不到 `characters/Alice/default/full_body.png` 对应的指纹，就无法给主图 URL 拼稳定变化的 `?v=`，版本切换后仍可能显示同一张缓存图。

修复：

- `lib/asset_fingerprints.py`
  - 将媒体目录扫描从“一层/一级子目录”改为递归扫描。
  - 任意层级遇到 `versions/` 都跳过。
  - 现在能扫描：

```text
characters/{角色}/{form_id}/full_body.png
characters/{角色}/{form_id}/three_view.png
characters/{角色}/{form_id}/input_refs/*.png
```

- `tests/test_asset_fingerprints.py`
  - 新增测试：扫描 `characters/Hero/default/full_body.png` 与 `three_view.png`。
  - 新增测试：跳过嵌套 `versions/`。

实测当前项目 `/home/czy/pindou/projects/3-5987f6c8` 已可扫描到：

```text
characters/宁一宵/default/full_body.png
characters/宁一宵/default/three_view.png
characters/苏洄/default/full_body.png
```

本次验证：

```bash
uv run ruff check lib/asset_fingerprints.py tests/test_asset_fingerprints.py lib/version_manager.py tests/test_version_manager_more.py tests/test_versions_router.py
uv run pytest tests/test_asset_fingerprints.py tests/test_version_manager_more.py tests/test_versions_router.py
```

结果：

- Python ruff 通过。
- 指纹/版本管理/版本路由测试 23 个通过。

## 最终状态检查

本次重新核对后，版本切换链路已经闭合：

- `VersionManager.restore_version()` 还原后会刷新当前文件的 `mtime_ns`，前端用它做缓存指纹，避免继续命中旧图。
- `compute_asset_fingerprints()` 已递归扫描 `characters/{角色}/{form_id}/full_body.png`、`three_view.png`，新角色目录结构能被前端拿到。
- `VersionTimeMachine` 会在资源指纹变化时重置本地版本列表并重新拉取，因此切版本后显示内容会跟着更新。
- 这次只读复核没有发现新的代码缺口；当前前端已可以正常在不同版本间切换。

## 回退注意事项

如需回退本次改造，重点回退以下文件：

- 新增文件：
  - `lib/character_assets.py`
  - `alembic/versions/36d8f84efb2c_add_forms_json_to_assets.py`
- 后端核心：
  - `lib/project_manager.py`
  - `lib/prompt_builders.py`
  - `lib/prompt_builders_script.py`
  - `lib/script_models.py`
  - `lib/data_validator.py`
  - `lib/status_calculator.py`
  - `lib/media_generator.py`
  - `lib/version_manager.py`
  - `server/services/generation_tasks.py`
  - `server/routers/characters.py`
  - `server/routers/generate.py`
  - `server/routers/assets.py`
  - `server/routers/files.py`
  - `server/routers/versions.py`
- Agent：
  - `server/agent_runtime/sdk_tools/enqueue_assets.py`
  - `server/agent_runtime/sdk_tools/__init__.py`
  - `agent_runtime_profile/` 下本次修改的 agents / skills / CLAUDE 文档。
- 前端：
  - `frontend/src/types/project.ts`
  - `frontend/src/types/script.ts`
  - `frontend/src/types/asset.ts`
  - `frontend/src/api.ts`
  - `frontend/src/components/canvas/lorebook/CharacterCard.tsx`
  - `frontend/src/components/canvas/lorebook/CharactersPage.tsx`
  - `frontend/src/components/canvas/StudioCanvasRouter.tsx`
  - `frontend/src/components/assets/AssetCard.tsx`
  - `frontend/src/components/canvas/reference/ReferencePanel.tsx`
  - `frontend/src/i18n/{zh,en,vi}/dashboard.ts`

数据库回退：

- 如果已经执行过迁移，回退需要移除 `assets.forms_json` 字段或执行 Alembic downgrade。
- 回退前建议先导出项目和全局资产库，因为 character 的 forms 图片路径已经会写入新目录结构。

数据回退：

- 新结构角色图片在 `characters/{角色}/{form_id}/full_body.png` 和 `characters/{角色}/{form_id}/three_view.png`。
- 若回退到旧版本，需要手动选择默认形态的 `full_body` 写回旧字段 `character_sheet`。
- `input_refs` 对应旧 `reference_image` 已变为数组；旧版本只能保留其中一张时，建议选择最主要的一张。
