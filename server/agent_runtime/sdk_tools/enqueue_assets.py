"""SDK MCP tools for asset image generation (character / scene / prop)."""

from __future__ import annotations

from typing import Any

from claude_agent_sdk import tool

from lib.asset_types import ASSET_SPECS, AssetSpec
from lib.character_assets import CHARACTER_REF_SLOTS, character_ref_resource_id, validate_form_id, validate_ref_slot
from lib.generation_queue_client import (
    BatchTaskSpec,
    batch_enqueue_and_wait,
)
from lib.project_manager import ProjectManager
from server.agent_runtime.sdk_tools._context import ToolContext, tool_error

# Asset-type emoji shown in tool output. Other display fields (bucket_key,
# label_zh, subdir) come from lib.asset_types.ASSET_SPECS — the cross-app
# source of truth.
_EMOJI: dict[str, str] = {"character": "🧑", "scene": "🏠", "prop": "📦"}

ALL_TYPES: tuple[str, ...] = ("scene", "prop")

_PENDING_DISPATCH = {
    "scene": lambda pm, name: pm.get_pending_project_scenes(name),
    "prop": lambda pm, name: pm.get_pending_project_props(name),
}


def _get_pending(pm: ProjectManager, project_name: str, asset_type: str) -> list[dict]:
    return _PENDING_DISPATCH[asset_type](pm, project_name)


def _build_specs(
    pm: ProjectManager,
    project_name: str,
    asset_type: str,
    names: list[str] | None,
    warnings: list[str],
) -> list[BatchTaskSpec]:
    spec: AssetSpec = ASSET_SPECS[asset_type]
    project = pm.load_project(project_name)
    assets_dict = project.get(spec.bucket_key, {})

    if names:
        resolved: list[str] = []
        for name in names:
            if name not in assets_dict:
                warnings.append(f"⚠️  {spec.label_zh} '{name}' 不存在于 project.json 中，跳过")
                continue
            if not assets_dict[name].get("description"):
                warnings.append(f"⚠️  {spec.label_zh} '{name}' 缺少描述，跳过")
                continue
            resolved.append(name)
    else:
        pending = _get_pending(pm, project_name, asset_type)
        resolved = []
        for item in pending:
            name = item["name"]
            if not assets_dict.get(name, {}).get("description"):
                warnings.append(f"⚠️  {spec.label_zh} '{name}' 缺少描述，跳过")
                continue
            resolved.append(name)

    return [
        BatchTaskSpec(
            task_type=spec.asset_type,
            media_type="image",
            resource_id=name,
            payload={"prompt": assets_dict[name]["description"]},
        )
        for name in resolved
    ]


def list_pending_assets_tool(ctx: ToolContext):
    @tool(
        "list_pending_assets",
        "列出项目内待生成设计图的场景/道具。角色参考图请使用 list_pending_character_refs。",
        {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["scene", "prop"],
                    "description": "资产类型；不传则列出所有类型的 pending",
                },
            },
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            asset_type = args.get("type")
            types = (asset_type,) if asset_type else ALL_TYPES
            lines: list[str] = []
            total = 0
            for t in types:
                spec = ASSET_SPECS[t]
                pending = _get_pending(ctx.pm, ctx.project_name, t)
                if not pending:
                    lines.append(f"✅ 项目 '{ctx.project_name}' 所有{spec.label_zh}都已有设计图")
                    continue
                total += len(pending)
                lines.append(f"\n📋 待生成的{spec.label_zh} ({len(pending)} 个):")
                for item in pending:
                    desc = item.get("description", "") or ""
                    desc_preview = desc[:60] + "..." if len(desc) > 60 else desc
                    lines.append(f"  {_EMOJI[t]} {item['name']} — {desc_preview}")
            if not asset_type and total == 0:
                lines.append(f"\n✅ 项目 '{ctx.project_name}' 所有资产均已有设计图")
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}
        except Exception as exc:  # noqa: BLE001
            return tool_error("list_pending_assets", exc)

    return _handler


def generate_assets_tool(ctx: ToolContext):
    @tool(
        "generate_assets",
        "批量生成场景/道具设计图。角色参考图请使用 generate_character_refs。"
        "type 省略则按 scene→prop 顺序每类独立 batch；"
        "names 指定具体名称（必须同时给 type）；all=true 表示该 type 的全部 pending。",
        {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["scene", "prop"],
                    "description": "资产类型；不传等于全部三类",
                },
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "目标资产名称列表；必须配合 type 使用",
                },
                "all": {
                    "type": "boolean",
                    "description": "是否扫描所有 pending（与 names 互斥；默认 false 但当未提供 names 时等同 true）",
                },
            },
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            asset_type = args.get("type")
            # ``dict.fromkeys`` 保序去重，避免同名重复入队但仍尊重调用方意图的顺序。
            raw_names = args.get("names")
            names: list[str] | None = list(dict.fromkeys(raw_names)) if raw_names else None
            all_flag = bool(args.get("all"))
            if names and not asset_type:
                return {
                    "content": [{"type": "text", "text": "names 必须配合 type 使用"}],
                    "is_error": True,
                }
            if names and all_flag:
                return {
                    "content": [{"type": "text", "text": "all 与 names 互斥，不能同时使用"}],
                    "is_error": True,
                }

            types = (asset_type,) if asset_type else ALL_TYPES
            warnings: list[str] = []
            total_success = 0
            total_failure = 0
            details: list[str] = []

            for t in types:
                spec = ASSET_SPECS[t]
                specs = _build_specs(ctx.pm, ctx.project_name, t, names, warnings)
                if not specs:
                    continue

                successes_acc, failures_acc = await batch_enqueue_and_wait(
                    project_name=ctx.project_name,
                    specs=specs,
                )

                for br in successes_acc:
                    version = (br.result or {}).get("version")
                    version_text = f" (v{version})" if version is not None else ""
                    file_path = (br.result or {}).get("file_path") or f"{spec.subdir}/{br.resource_id}.png"
                    details.append(f"  ✓ {spec.label_zh} '{br.resource_id}' → {file_path}{version_text}")
                for br in failures_acc:
                    details.append(f"  ✗ {spec.label_zh} '{br.resource_id}': {br.error}")
                total_success += len(successes_acc)
                total_failure += len(failures_acc)

            header = f"generate_assets summary: {total_success} succeeded, {total_failure} failed"
            body_parts = warnings + ([header] if (total_success or total_failure) else [])
            if total_success == 0 and total_failure == 0:
                body_parts.append("✅ 没有需要生成的资产")
            body_parts.extend(details)
            return {
                "content": [{"type": "text", "text": "\n".join(body_parts)}],
                "is_error": total_failure > 0,
            }
        except Exception as exc:  # noqa: BLE001
            return tool_error("generate_assets", exc)

    return _handler


def list_pending_character_refs_tool(ctx: ToolContext):
    @tool(
        "list_pending_character_refs",
        "列出项目内缺失的角色形态参考图槽位（full_body / three_view）。",
        {
            "type": "object",
            "properties": {
                "current_episode_only": {
                    "type": "boolean",
                    "description": "是否只列当前集实际使用的角色形态；未提供 script_file 时忽略",
                },
                "script_file": {
                    "type": "string",
                    "description": "剧本文件名，例如 episode_1.json，用于扫描当前集实际使用的角色形态",
                },
            },
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            pending = ctx.pm.get_pending_character_refs(ctx.project_name)
            if args.get("current_episode_only") and args.get("script_file"):
                used = _collect_used_character_forms(ctx.pm, ctx.project_name, str(args["script_file"]))
                pending = [item for item in pending if (item["name"], item["form_id"]) in used]
            if not pending:
                return {"content": [{"type": "text", "text": "✅ 没有缺失的角色形态参考图"}]}
            lines = [f"📋 待生成角色形态参考图 ({len(pending)} 个槽位):"]
            for item in pending:
                form = item.get("form") or {}
                label = form.get("label") or item["form_id"]
                lines.append(f"  🧑 {item['name']}/{item['form_id']}（{label}）/{item['slot']}")
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}
        except Exception as exc:  # noqa: BLE001
            return tool_error("list_pending_character_refs", exc)

    return _handler


def _collect_used_character_forms(pm: ProjectManager, project_name: str, script_file: str) -> set[tuple[str, str]]:
    script = pm.load_script(project_name, script_file)
    items = script.get("scenes") if isinstance(script.get("scenes"), list) else []
    used: set[tuple[str, str]] = set()
    for item in items:
        char_names = item.get("characters_in_scene") or []
        forms = item.get("character_forms") if isinstance(item.get("character_forms"), dict) else {}
        for name in char_names:
            form_id = forms.get(name) or "default"
            used.add((str(name), str(form_id)))
    return used


def _build_character_ref_specs(
    pm: ProjectManager,
    project_name: str,
    targets: list[dict[str, Any]] | None,
    warnings: list[str],
) -> list[BatchTaskSpec]:
    project = pm.load_project(project_name)
    characters = project.get("characters") or {}
    specs: list[BatchTaskSpec] = []

    if targets:
        for target in targets:
            character = str(target.get("character") or "").strip()
            try:
                form_id = validate_form_id(str(target.get("form_id") or "default"))
            except ValueError as exc:
                warnings.append(f"⚠️  {exc}")
                continue
            raw_slots = target.get("slots") or list(CHARACTER_REF_SLOTS)
            slots: list[str] = []
            for raw_slot in raw_slots:
                try:
                    slots.append(validate_ref_slot(str(raw_slot)))
                except ValueError as exc:
                    warnings.append(f"⚠️  {exc}")
            char_data = characters.get(character)
            if not isinstance(char_data, dict):
                warnings.append(f"⚠️  角色 '{character}' 不存在于 project.json 中，跳过")
                continue
            forms = char_data.get("forms") if isinstance(char_data.get("forms"), dict) else {}
            if form_id not in forms:
                warnings.append(f"⚠️  角色 '{character}' 不存在形态 '{form_id}'，跳过")
                continue
            for slot in dict.fromkeys(slots):
                specs.append(
                    BatchTaskSpec(
                        task_type="character_ref",
                        media_type="image",
                        resource_id=character_ref_resource_id(character, form_id, slot),
                        payload={"character": character, "form_id": form_id, "slot": slot},
                    )
                )
        return specs

    for item in pm.get_pending_character_refs(project_name):
        character = item["name"]
        form_id = item["form_id"]
        slot = item["slot"]
        specs.append(
            BatchTaskSpec(
                task_type="character_ref",
                media_type="image",
                resource_id=character_ref_resource_id(character, form_id, slot),
                payload={"character": character, "form_id": form_id, "slot": slot},
            )
        )
    return specs


def generate_character_refs_tool(ctx: ToolContext):
    @tool(
        "generate_character_refs",
        "批量生成角色形态参考图。未提供 targets 时生成全部 pending；可指定角色、形态和槽位。",
        {
            "type": "object",
            "properties": {
                "targets": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "character": {"type": "string"},
                            "form_id": {"type": "string"},
                            "slots": {
                                "type": "array",
                                "items": {"type": "string", "enum": ["full_body", "three_view"]},
                            },
                        },
                        "required": ["character", "form_id"],
                    },
                    "description": "目标列表，例如 [{character:'苏洄', form_id:'default', slots:['full_body','three_view']}]",
                },
                "current_episode_only": {
                    "type": "boolean",
                    "description": "未提供 targets 时，是否只生成 script_file 中实际使用的角色形态",
                },
                "script_file": {"type": "string", "description": "剧本文件名"},
            },
        },
    )
    async def _handler(args: dict[str, Any]) -> dict[str, Any]:
        try:
            warnings: list[str] = []
            targets = args.get("targets") if isinstance(args.get("targets"), list) else None
            specs = _build_character_ref_specs(ctx.pm, ctx.project_name, targets, warnings)
            if not targets and args.get("current_episode_only") and args.get("script_file"):
                used = _collect_used_character_forms(ctx.pm, ctx.project_name, str(args["script_file"]))
                specs = [spec for spec in specs if (spec.payload.get("character"), spec.payload.get("form_id")) in used]

            if not specs:
                return {"content": [{"type": "text", "text": "\n".join(warnings + ["✅ 没有需要生成的角色参考图"])}]}

            successes_acc, failures_acc = await batch_enqueue_and_wait(
                project_name=ctx.project_name,
                specs=specs,
            )
            details: list[str] = []
            for br in successes_acc:
                version = (br.result or {}).get("version")
                version_text = f" (v{version})" if version is not None else ""
                file_path = (br.result or {}).get("file_path") or f"characters/{br.resource_id}.png"
                details.append(f"  ✓ 角色参考图 '{br.resource_id}' → {file_path}{version_text}")
            for br in failures_acc:
                details.append(f"  ✗ 角色参考图 '{br.resource_id}': {br.error}")
            header = f"generate_character_refs summary: {len(successes_acc)} succeeded, {len(failures_acc)} failed"
            return {
                "content": [{"type": "text", "text": "\n".join(warnings + [header] + details)}],
                "is_error": bool(failures_acc),
            }
        except Exception as exc:  # noqa: BLE001
            return tool_error("generate_character_refs", exc)

    return _handler


__all__ = [
    "ALL_TYPES",
    "list_pending_assets_tool",
    "generate_assets_tool",
    "list_pending_character_refs_tool",
    "generate_character_refs_tool",
]
