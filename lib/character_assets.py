"""角色多形态资产结构工具。

项目内角色从单一 ``character_sheet`` 升级为:

characters[name].forms[form_id].refs[slot].path

slot 固定为:
- full_body: 单人全身主参考图；群体角色为群体全身参考图
- three_view: 单体角色三视图

单体角色默认用于分镜/视频的槽位为 ``three_view``，群体角色默认为 ``full_body``。
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

DEFAULT_FORM_ID = "default"
CHARACTER_REF_SLOTS = ("full_body", "three_view")
DEFAULT_STORYBOARD_REF_SLOT = "three_view"
CHARACTER_KINDS = ("single", "group")
DEFAULT_CHARACTER_KIND = "single"
GROUP_CHARACTER_KIND = "group"

REF_PURPOSES = {
    "full_body": "storyboard_reference",
    "three_view": "consistency_review",
}


def validate_form_id(form_id: str) -> str:
    form_id = (form_id or "").strip()
    if not form_id or "/" in form_id or "\\" in form_id or "\0" in form_id or ".." in form_id:
        raise ValueError(f"invalid form_id: {form_id!r}")
    return form_id


def validate_ref_slot(slot: str) -> str:
    slot = (slot or "").strip()
    if slot not in CHARACTER_REF_SLOTS:
        raise ValueError(f"invalid character ref slot: {slot!r}")
    return slot


def get_character_kind(entry: dict[str, Any] | None) -> str:
    """Return normalized character kind; legacy data defaults to single."""
    if not isinstance(entry, dict):
        return DEFAULT_CHARACTER_KIND
    kind = str(entry.get("character_kind") or DEFAULT_CHARACTER_KIND).strip()
    return kind if kind in CHARACTER_KINDS else DEFAULT_CHARACTER_KIND


def default_storyboard_ref_slot_for_kind(character_kind: str) -> str:
    return "full_body" if character_kind == GROUP_CHARACTER_KIND else DEFAULT_STORYBOARD_REF_SLOT


def make_empty_ref(slot: str) -> dict[str, str]:
    slot = validate_ref_slot(slot)
    return {"path": "", "purpose": REF_PURPOSES[slot]}


def make_default_refs() -> dict[str, dict[str, str]]:
    return {slot: make_empty_ref(slot) for slot in CHARACTER_REF_SLOTS}


def make_default_form(
    description: str = "",
    *,
    label: str = "默认造型",
    character_kind: str = DEFAULT_CHARACTER_KIND,
) -> dict[str, Any]:
    return {
        "label": label,
        "description": description or "",
        "storyboard_ref_slot": default_storyboard_ref_slot_for_kind(character_kind),
        "input_refs": [],
        "refs": make_default_refs(),
    }


def normalize_form(
    form: dict[str, Any] | None,
    *,
    description: str = "",
    label: str = "默认造型",
    character_kind: str = DEFAULT_CHARACTER_KIND,
) -> dict[str, Any]:
    data = deepcopy(form) if isinstance(form, dict) else {}
    refs = data.get("refs") if isinstance(data.get("refs"), dict) else {}
    normalized = {
        "label": str(data.get("label") or label),
        "description": str(data.get("description") or description or ""),
        "storyboard_ref_slot": data.get("storyboard_ref_slot") or default_storyboard_ref_slot_for_kind(character_kind),
        "input_refs": data.get("input_refs") if isinstance(data.get("input_refs"), list) else [],
        "refs": {},
    }
    if normalized["storyboard_ref_slot"] not in CHARACTER_REF_SLOTS:
        normalized["storyboard_ref_slot"] = default_storyboard_ref_slot_for_kind(character_kind)
    for slot in CHARACTER_REF_SLOTS:
        value = refs.get(slot) if isinstance(refs, dict) else {}
        if isinstance(value, dict):
            normalized["refs"][slot] = {
                "path": str(value.get("path") or ""),
                "purpose": str(value.get("purpose") or REF_PURPOSES[slot]),
            }
        else:
            normalized["refs"][slot] = make_empty_ref(slot)
    normalized["input_refs"] = [str(p) for p in normalized["input_refs"] if isinstance(p, str) and p]
    return normalized


def make_character_entry(description: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    source = source or {}
    character_kind = get_character_kind(source)
    legacy_sheet = str(source.get("character_sheet") or "")
    legacy_reference = str(source.get("reference_image") or "")
    forms_src = source.get("forms") if isinstance(source.get("forms"), dict) else {}
    forms: dict[str, Any] = {}
    if forms_src:
        for form_id, form in forms_src.items():
            try:
                normalized_id = validate_form_id(str(form_id))
            except ValueError:
                continue
            forms[normalized_id] = normalize_form(form, character_kind=character_kind)
    if not forms:
        forms[DEFAULT_FORM_ID] = make_default_form(description, character_kind=character_kind)
    default_like = forms.get(str(source.get("default_form") or DEFAULT_FORM_ID)) or forms.get(DEFAULT_FORM_ID)
    if isinstance(default_like, dict):
        if legacy_sheet and not default_like["refs"]["full_body"]["path"]:
            default_like["refs"]["full_body"]["path"] = legacy_sheet
        if legacy_reference and legacy_reference not in default_like["input_refs"]:
            default_like["input_refs"].append(legacy_reference)
    default_form = str(source.get("default_form") or DEFAULT_FORM_ID)
    if default_form not in forms:
        default_form = next(iter(forms.keys()), DEFAULT_FORM_ID)
    return {
        "description": description or "",
        "voice_style": str(source.get("voice_style") or ""),
        "character_kind": character_kind,
        "default_form": default_form,
        "forms": forms,
    }


def ensure_character_forms(entry: dict[str, Any]) -> dict[str, Any]:
    character_kind = get_character_kind(entry)
    entry["character_kind"] = character_kind
    legacy_sheet = str(entry.get("character_sheet") or "")
    legacy_reference = str(entry.get("reference_image") or "")
    if not isinstance(entry.get("forms"), dict) or not entry["forms"]:
        entry["forms"] = {
            DEFAULT_FORM_ID: make_default_form(str(entry.get("description") or ""), character_kind=character_kind)
        }
    for form_id, form in list(entry["forms"].items()):
        try:
            normalized_id = validate_form_id(str(form_id))
        except ValueError:
            entry["forms"].pop(form_id, None)
            continue
        normalized = normalize_form(form, character_kind=character_kind)
        if normalized_id != form_id:
            entry["forms"].pop(form_id, None)
        entry["forms"][normalized_id] = normalized
    if not entry["forms"]:
        entry["forms"][DEFAULT_FORM_ID] = make_default_form(
            str(entry.get("description") or ""),
            character_kind=character_kind,
        )
    default_form = str(entry.get("default_form") or DEFAULT_FORM_ID)
    if default_form not in entry["forms"]:
        default_form = next(iter(entry["forms"].keys()))
    entry["default_form"] = default_form
    default = entry["forms"][default_form]
    if legacy_sheet and not default["refs"]["full_body"]["path"]:
        default["refs"]["full_body"]["path"] = legacy_sheet
    if legacy_reference and legacy_reference not in default["input_refs"]:
        default["input_refs"].append(legacy_reference)
    entry.pop("character_sheet", None)
    entry.pop("reference_image", None)
    return entry


def get_form(entry: dict[str, Any], form_id: str | None = None) -> tuple[str, dict[str, Any]]:
    ensure_character_forms(entry)
    resolved = form_id or entry.get("default_form") or DEFAULT_FORM_ID
    if resolved not in entry["forms"]:
        raise KeyError(f"character form not found: {resolved}")
    return resolved, entry["forms"][resolved]


def get_ref_path(entry: dict[str, Any], form_id: str | None, slot: str) -> str:
    _, form = get_form(entry, form_id)
    slot = validate_ref_slot(slot)
    ref = form.get("refs", {}).get(slot, {})
    return str(ref.get("path") or "") if isinstance(ref, dict) else ""


def set_ref_path(entry: dict[str, Any], form_id: str, slot: str, path: str) -> None:
    ensure_character_forms(entry)
    form_id = validate_form_id(form_id)
    slot = validate_ref_slot(slot)
    if form_id not in entry["forms"]:
        entry["forms"][form_id] = make_default_form(character_kind=get_character_kind(entry))
    form = entry["forms"][form_id]
    form.setdefault("refs", make_default_refs())
    form["refs"][slot] = {"path": path, "purpose": REF_PURPOSES[slot]}


def get_storyboard_ref_path(entry: dict[str, Any], form_id: str | None = None) -> tuple[str, str, str]:
    resolved_form_id, form = get_form(entry, form_id)
    slot = form.get("storyboard_ref_slot") or DEFAULT_STORYBOARD_REF_SLOT
    if slot not in CHARACTER_REF_SLOTS:
        slot = DEFAULT_STORYBOARD_REF_SLOT
    rel_path = get_ref_path(entry, resolved_form_id, slot)
    if not rel_path and slot != "full_body":
        fallback = get_ref_path(entry, resolved_form_id, "full_body")
        if fallback:
            return resolved_form_id, "full_body", fallback
    return resolved_form_id, slot, rel_path


def character_ref_resource_id(character: str, form_id: str, slot: str) -> str:
    return f"{character}/{validate_form_id(form_id)}/{validate_ref_slot(slot)}"


def character_ref_relative_path(character: str, form_id: str, slot: str, *, ext: str = ".png") -> str:
    return f"characters/{character}/{validate_form_id(form_id)}/{validate_ref_slot(slot)}{ext}"


def collect_existing_paths_from_forms(forms: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for form in forms.values():
        if not isinstance(form, dict):
            continue
        for item in form.get("input_refs") or []:
            if isinstance(item, str) and item:
                paths.append(item)
        refs = form.get("refs") if isinstance(form.get("refs"), dict) else {}
        for slot in CHARACTER_REF_SLOTS:
            ref = refs.get(slot)
            if isinstance(ref, dict) and ref.get("path"):
                paths.append(str(ref["path"]))
    return paths


def path_exists(project_dir: Path, rel_path: str) -> bool:
    if not rel_path:
        return False
    path = project_dir / rel_path
    try:
        path.resolve().relative_to(project_dir.resolve())
    except ValueError:
        return False
    return path.exists()
