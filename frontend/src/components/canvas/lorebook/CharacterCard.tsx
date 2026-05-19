import { useEffect, useId, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ImagePlus, Plus, Trash2, Upload, User } from "lucide-react";
import { API } from "@/api";
import { AddToLibraryButton } from "@/components/assets/AddToLibraryButton";
import { VersionTimeMachine } from "@/components/canvas/timeline/VersionTimeMachine";
import { AspectFrame } from "@/components/ui/AspectFrame";
import { GenerateButton } from "@/components/ui/GenerateButton";
import { ImageFlipReveal } from "@/components/ui/ImageFlipReveal";
import { PreviewableImageFrame } from "@/components/ui/PreviewableImageFrame";
import { useAppStore } from "@/stores/app-store";
import { useProjectsStore } from "@/stores/projects-store";
import { errMsg } from "@/utils/async";
import type { Character, CharacterForm, CharacterRefSlot } from "@/types";

interface CharacterSavePayload {
  description: string;
  voiceStyle: string;
}

interface CharacterCardProps {
  name: string;
  character: Character;
  projectName: string;
  onSave: (name: string, payload: CharacterSavePayload) => Promise<void>;
  onGenerate?: (name: string) => void;
  onGenerateRef?: (name: string, formId: string, slot: CharacterRefSlot) => void;
  onAddForm?: (name: string, formId: string, label: string, description: string) => Promise<void>;
  onUpdateForm?: (
    name: string,
    formId: string,
    updates: {
      label?: string;
      description?: string;
      storyboard_ref_slot?: CharacterRefSlot;
      default_form?: boolean;
    },
  ) => Promise<void>;
  onDeleteForm?: (name: string, formId: string) => Promise<void>;
  onUploadFormRef?: (name: string, formId: string, slot: CharacterRefSlot, file: File) => Promise<void>;
  onUploadInputRef?: (name: string, formId: string, file: File) => Promise<void>;
  onDeleteInputRef?: (name: string, formId: string, path: string) => Promise<void>;
  onReload?: () => Promise<void> | void;
  generatingRefKeys?: Set<string>;
}

const FIELD_STYLE: React.CSSProperties = {
  background:
    "linear-gradient(180deg, oklch(0.20 0.011 265 / 0.6), oklch(0.18 0.010 265 / 0.45))",
  border: "1px solid var(--color-hairline)",
  color: "var(--color-text)",
  boxShadow: "inset 0 1px 2px oklch(0 0 0 / 0.2)",
};

const SLOT_LABEL_KEYS: Record<CharacterRefSlot, string> = {
  full_body: "character_ref_slot_full_body",
  three_view: "character_ref_slot_three_view",
};

const REF_SLOTS: CharacterRefSlot[] = ["full_body", "three_view"];

function makeFallbackForm(description: string): CharacterForm {
  return {
    label: "默认造型",
    description,
    storyboard_ref_slot: "full_body",
    input_refs: [],
    refs: {
      full_body: { path: "", purpose: "storyboard_reference" },
      three_view: { path: "", purpose: "consistency_review" },
    },
  };
}

type NormalizedCharacter = Character & { default_form: string; forms: Record<string, CharacterForm> };

function normalizeCharacter(character: Character): NormalizedCharacter {
  if (character.forms && Object.keys(character.forms).length > 0) {
    return character as NormalizedCharacter;
  }
  const fallback = makeFallbackForm(character.description);
  if (character.character_sheet) {
    fallback.refs.full_body.path = character.character_sheet;
  }
  if (character.reference_image) {
    fallback.input_refs = [character.reference_image];
  }
  return {
    ...character,
    default_form: character.default_form || "default",
    forms: { default: fallback },
  };
}

export function CharacterCard({
  name,
  character,
  projectName,
  onSave,
  onGenerate,
  onGenerateRef,
  onAddForm = async () => {},
  onUpdateForm = async () => {},
  onDeleteForm = async () => {},
  onUploadFormRef = async () => {},
  onUploadInputRef = async () => {},
  onDeleteInputRef = async () => {},
  onReload,
  generatingRefKeys,
}: CharacterCardProps) {
  const { t } = useTranslation(["dashboard", "assets", "common"]);
  const generateRef = onGenerateRef ?? ((charName: string) => onGenerate?.(charName));
  const fingerprints = useProjectsStore((s) => s.assetFingerprints);
  const normalized = useMemo(() => normalizeCharacter(character), [character]);
  const formEntries = useMemo(() => Object.entries(normalized.forms), [normalized.forms]);
  const [activeFormId, setActiveFormId] = useState(normalized.default_form || formEntries[0]?.[0] || "default");
  const activeForm = normalized.forms[activeFormId] ?? formEntries[0]?.[1] ?? makeFallbackForm(normalized.description);
  const [description, setDescription] = useState(normalized.description);
  const [voiceStyle, setVoiceStyle] = useState(normalized.voice_style ?? "");
  const [saving, setSaving] = useState(false);
  const [newFormId, setNewFormId] = useState("");
  const [newFormLabel, setNewFormLabel] = useState("");
  const descId = useId();
  const voiceId = useId();

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDescription(normalized.description);
    setVoiceStyle(normalized.voice_style ?? "");
  }, [normalized.description, normalized.voice_style]);

  useEffect(() => {
    if (!normalized.forms[activeFormId]) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActiveFormId(normalized.default_form || formEntries[0]?.[0] || "default");
    }
  }, [activeFormId, formEntries, normalized.default_form, normalized.forms]);

  const isDirty = description !== normalized.description || voiceStyle !== (normalized.voice_style ?? "");
  const previewPath = activeForm.refs[activeForm.storyboard_ref_slot]?.path || activeForm.refs.full_body?.path || "";
  const previewUrl = previewPath ? API.getFileUrl(projectName, previewPath, fingerprints[previewPath]) : null;

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(name, { description, voiceStyle });
    } finally {
      setSaving(false);
    }
  };

  const handleAddForm = async () => {
    const formId = newFormId.trim();
    if (!formId) return;
    await onAddForm(name, formId, newFormLabel.trim() || formId, "");
    setNewFormId("");
    setNewFormLabel("");
    setActiveFormId(formId);
  };

  return (
    <div
      id={`character-${name}`}
      className="relative overflow-hidden rounded-xl p-5"
      style={{
        background:
          "linear-gradient(180deg, oklch(0.22 0.012 265 / 0.55), oklch(0.19 0.010 265 / 0.40))",
        border: "1px solid var(--color-hairline-soft)",
        boxShadow:
          "inset 0 1px 0 oklch(1 0 0 / 0.04), 0 12px 30px -12px oklch(0 0 0 / 0.4)",
      }}
    >
      <span
        aria-hidden
        className="pointer-events-none absolute inset-x-5 top-0 h-px"
        style={{ background: "linear-gradient(90deg, transparent, var(--color-accent-soft), transparent)" }}
      />

      <div className="mb-4 flex items-center gap-2.5">
        <span
          aria-hidden
          className="grid h-7 w-7 shrink-0 place-items-center rounded-md"
          style={{
            background: "var(--color-accent-dim)",
            border: "1px solid var(--color-accent-soft)",
            color: "var(--color-accent-2)",
          }}
        >
          <User className="h-3.5 w-3.5" />
        </span>
        <h3 className="display-serif min-w-0 flex-1 truncate text-[16px] font-semibold tracking-tight text-text">
          {name}
        </h3>
        <AddToLibraryButton
          resourceType="character"
          resourceId={name}
          projectName={projectName}
          initialDescription={normalized.description}
          initialVoiceStyle={normalized.voice_style ?? ""}
          sheetPath={previewPath}
          className="focus-ring inline-flex h-7 w-7 items-center justify-center rounded-md text-[var(--color-text-3)] transition-colors hover:bg-[oklch(1_0_0_/_0.05)]"
        />
      </div>

      <div className="mb-4 overflow-hidden rounded-lg" style={{ border: "1px solid var(--color-hairline-soft)" }}>
        <PreviewableImageFrame src={previewUrl} alt={`${name} ${t("dashboard:character_active_reference")}`}>
          <AspectFrame ratio="16:9">
            <ImageFlipReveal
              src={previewUrl}
              alt={`${name} ${t("dashboard:character_active_reference")}`}
              className="h-full w-full object-contain"
              fallback={
                <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-text-4">
                  <User className="h-10 w-10" />
                  <span className="text-xs">{t("dashboard:character_ref_empty")}</span>
                </div>
              }
            />
          </AspectFrame>
        </PreviewableImageFrame>
      </div>

      <CapsLabel htmlFor={descId}>{t("dashboard:description")}</CapsLabel>
      <textarea
        id={descId}
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        rows={3}
        className="focus-ring mt-1.5 w-full resize-y rounded-lg px-3 py-2 text-[13px] leading-[1.55] outline-none"
        style={FIELD_STYLE}
        placeholder={t("dashboard:character_desc_placeholder")}
      />

      <div className="mt-3">
        <CapsLabel htmlFor={voiceId}>{t("dashboard:voice_style")}</CapsLabel>
        <input
          id={voiceId}
          type="text"
          value={voiceStyle}
          onChange={(e) => setVoiceStyle(e.target.value)}
          className="focus-ring mt-1.5 w-full rounded-lg px-3 py-2 text-[13px] outline-none"
          style={FIELD_STYLE}
          placeholder={t("dashboard:voice_style_example")}
        />
      </div>

      {isDirty && (
        <button
          type="button"
          onClick={() => void handleSave()}
          disabled={saving}
          className="focus-ring mt-3 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-medium disabled:opacity-50"
          style={{
            color: "oklch(0.14 0 0)",
            background: "linear-gradient(135deg, var(--color-accent-2), var(--color-accent))",
          }}
        >
          {saving ? t("common:saving") : t("common:save")}
        </button>
      )}

      <div className="mt-5">
        <CapsLabel>{t("dashboard:character_forms")}</CapsLabel>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {formEntries.map(([formId, form]) => (
            <button
              key={formId}
              type="button"
              onClick={() => setActiveFormId(formId)}
              className="focus-ring rounded-md border px-2 py-1 text-[12px]"
              style={{
                borderColor: formId === activeFormId ? "var(--color-accent-soft)" : "var(--color-hairline)",
                color: formId === activeFormId ? "var(--color-text)" : "var(--color-text-3)",
                background: formId === activeFormId ? "var(--color-accent-dim)" : "transparent",
              }}
            >
              {form.label || formId}
            </button>
          ))}
        </div>
      </div>

      <CharacterFormPanel
        key={activeFormId}
        projectName={projectName}
        characterName={name}
        formId={activeFormId}
        form={activeForm}
        defaultForm={normalized.default_form}
        fingerprints={fingerprints}
        generatingRefKeys={generatingRefKeys}
        onGenerateRef={generateRef}
        onUpdateForm={onUpdateForm}
        onDeleteForm={onDeleteForm}
        onUploadFormRef={onUploadFormRef}
        onUploadInputRef={onUploadInputRef}
        onDeleteInputRef={onDeleteInputRef}
        onReload={onReload}
      />

      <div className="mt-4 rounded-lg border border-hairline-soft p-3">
        <CapsLabel>{t("dashboard:add_character_form")}</CapsLabel>
        <div className="mt-2 grid grid-cols-[1fr_1fr_auto] gap-2">
          <input
            value={newFormId}
            onChange={(e) => setNewFormId(e.target.value)}
            className="focus-ring min-w-0 rounded-md px-2 py-1.5 text-[12px]"
            style={FIELD_STYLE}
            placeholder={t("dashboard:character_form_id")}
          />
          <input
            value={newFormLabel}
            onChange={(e) => setNewFormLabel(e.target.value)}
            className="focus-ring min-w-0 rounded-md px-2 py-1.5 text-[12px]"
            style={FIELD_STYLE}
            placeholder={t("dashboard:character_form_label")}
          />
          <button
            type="button"
            onClick={() => void handleAddForm().catch((err) => useAppStore.getState().pushToast(errMsg(err), "error"))}
            className="focus-ring inline-flex h-8 w-8 items-center justify-center rounded-md border border-hairline text-text-3"
            title={t("dashboard:add_character_form")}
            aria-label={t("dashboard:add_character_form")}
          >
            <Plus className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );
}

interface CharacterFormPanelProps {
  projectName: string;
  characterName: string;
  formId: string;
  form: CharacterForm;
  defaultForm: string;
  fingerprints: Record<string, number>;
  generatingRefKeys?: Set<string>;
  onGenerateRef: (name: string, formId: string, slot: CharacterRefSlot) => void;
  onUpdateForm: NonNullable<CharacterCardProps["onUpdateForm"]>;
  onDeleteForm: NonNullable<CharacterCardProps["onDeleteForm"]>;
  onUploadFormRef: NonNullable<CharacterCardProps["onUploadFormRef"]>;
  onUploadInputRef: NonNullable<CharacterCardProps["onUploadInputRef"]>;
  onDeleteInputRef: NonNullable<CharacterCardProps["onDeleteInputRef"]>;
  onReload?: () => Promise<void> | void;
}

function CharacterFormPanel({
  projectName,
  characterName,
  formId,
  form,
  defaultForm,
  fingerprints,
  generatingRefKeys,
  onGenerateRef,
  onUpdateForm,
  onDeleteForm,
  onUploadFormRef,
  onUploadInputRef,
  onDeleteInputRef,
  onReload,
}: CharacterFormPanelProps) {
  const { t } = useTranslation(["dashboard", "assets", "common"]);
  const [label, setLabel] = useState(form.label);
  const [description, setDescription] = useState(form.description);
  const [saving, setSaving] = useState(false);
  const [deletingInputRef, setDeletingInputRef] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const formDirty = label !== form.label || description !== form.description;

  const handleSaveForm = async () => {
    setSaving(true);
    try {
      await onUpdateForm(characterName, formId, { label, description });
    } finally {
      setSaving(false);
    }
  };

  const handleInputRef = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    await onUploadInputRef(characterName, formId, file);
  };

  const handleDeleteInputRef = async (path: string) => {
    setDeletingInputRef(path);
    try {
      await onDeleteInputRef(characterName, formId, path);
    } finally {
      setDeletingInputRef(null);
    }
  };

  return (
    <div className="mt-4 rounded-lg border border-hairline-soft p-3">
      <div className="flex items-center gap-2">
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          className="focus-ring min-w-0 flex-1 rounded-md px-2 py-1.5 text-[12px]"
          style={FIELD_STYLE}
        />
        <button
          type="button"
          onClick={() => void onUpdateForm(characterName, formId, { default_form: true })}
          disabled={defaultForm === formId}
          className="focus-ring rounded-md border border-hairline px-2 py-1.5 text-[11px] text-text-3 disabled:opacity-50"
        >
          {defaultForm === formId ? t("dashboard:default_form") : t("dashboard:set_default_form")}
        </button>
        {defaultForm !== formId && (
          <button
            type="button"
            onClick={() => void onDeleteForm(characterName, formId).catch((err) => useAppStore.getState().pushToast(errMsg(err), "error"))}
            className="focus-ring inline-flex h-7 w-7 items-center justify-center rounded-md text-text-4 hover:text-warm-bright"
            title={t("common:delete")}
            aria-label={t("common:delete")}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        rows={2}
        className="focus-ring mt-2 w-full resize-y rounded-md px-2 py-1.5 text-[12px] leading-[1.55]"
        style={FIELD_STYLE}
        placeholder={t("dashboard:character_form_desc")}
      />
      {formDirty && (
        <button
          type="button"
          onClick={() => void handleSaveForm()}
          disabled={saving}
          className="focus-ring mt-2 rounded-md border border-hairline px-2 py-1 text-[11px] text-text-3"
        >
          {saving ? t("common:saving") : t("common:save")}
        </button>
      )}

      <div className="mt-3 grid grid-cols-2 gap-3">
        {REF_SLOTS.map((slot) => (
          <CharacterRefSlotView
            key={slot}
            projectName={projectName}
            characterName={characterName}
            formId={formId}
            slot={slot}
            form={form}
            fingerprint={form.refs[slot]?.path ? fingerprints[form.refs[slot].path] : null}
            generating={generatingRefKeys?.has(`${characterName}/${formId}/${slot}`) ?? false}
            onGenerateRef={onGenerateRef}
            onUpdateForm={onUpdateForm}
            onUploadFormRef={onUploadFormRef}
            onRestore={onReload}
          />
        ))}
      </div>

      <div className="mt-3">
        <div className="flex items-center justify-between">
          <CapsLabel>{t("dashboard:character_input_refs")}</CapsLabel>
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="focus-ring inline-flex items-center gap-1 rounded-md border border-hairline px-2 py-1 text-[11px] text-text-3"
          >
            <Upload className="h-3 w-3" />
            {t("dashboard:upload_input_ref")}
          </button>
          <input
            ref={inputRef}
            type="file"
            accept=".png,.jpg,.jpeg,.webp"
            className="hidden"
            aria-label={t("dashboard:upload_input_ref")}
            onChange={(event) => void handleInputRef(event).catch((err) => useAppStore.getState().pushToast(errMsg(err), "error"))}
          />
        </div>
        <div className="mt-2 grid grid-cols-4 gap-2">
          {form.input_refs.map((path) => (
            <div key={path} className="group relative">
              <img
                src={API.getFileUrl(projectName, path, fingerprints[path])}
                alt={t("dashboard:character_input_refs")}
                className="aspect-square rounded-md border border-hairline object-cover"
              />
              <button
                type="button"
                onClick={() => void handleDeleteInputRef(path).catch((err) => useAppStore.getState().pushToast(errMsg(err), "error"))}
                disabled={deletingInputRef === path}
                title={t("dashboard:delete_input_ref")}
                aria-label={t("dashboard:delete_input_ref")}
                className="focus-ring absolute right-1 top-1 inline-flex h-6 w-6 items-center justify-center rounded-md border border-hairline bg-bg-grad-b/85 text-text-3 opacity-0 backdrop-blur transition-opacity hover:text-warm-bright disabled:opacity-50 group-hover:opacity-100 group-focus-within:opacity-100"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          ))}
          {form.input_refs.length === 0 && (
            <div className="col-span-4 rounded-md border border-dashed border-hairline p-3 text-center text-[11px] text-text-4">
              {t("dashboard:no_input_refs")}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

interface CharacterRefSlotViewProps {
  projectName: string;
  characterName: string;
  formId: string;
  slot: CharacterRefSlot;
  form: CharacterForm;
  fingerprint: number | null;
  generating: boolean;
  onGenerateRef: (name: string, formId: string, slot: CharacterRefSlot) => void;
  onUpdateForm: NonNullable<CharacterCardProps["onUpdateForm"]>;
  onUploadFormRef: NonNullable<CharacterCardProps["onUploadFormRef"]>;
  onRestore?: () => Promise<void> | void;
}

function CharacterRefSlotView({
  projectName,
  characterName,
  formId,
  slot,
  form,
  fingerprint,
  generating,
  onGenerateRef,
  onUpdateForm,
  onUploadFormRef,
  onRestore,
}: CharacterRefSlotViewProps) {
  const { t } = useTranslation(["dashboard", "common"]);
  const fileRef = useRef<HTMLInputElement>(null);
  const path = form.refs[slot]?.path || "";
  const url = path ? API.getFileUrl(projectName, path, fingerprint) : null;

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    await onUploadFormRef(characterName, formId, slot, file);
  };

  return (
    <div className="rounded-lg border border-hairline-soft p-2">
      <div className="mb-2 flex items-center justify-between gap-2">
        <CapsLabel>{t(SLOT_LABEL_KEYS[slot])}</CapsLabel>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => void onUpdateForm(characterName, formId, { storyboard_ref_slot: slot })}
            className="focus-ring rounded border border-hairline px-1.5 py-0.5 text-[10px] text-text-3"
          >
            {form.storyboard_ref_slot === slot ? t("storyboard_ref_active") : t("use_for_storyboard")}
          </button>
          <VersionTimeMachine
            projectName={projectName}
            resourceType="character_refs"
            resourceId={`${characterName}/${formId}/${slot}`}
            onRestore={onRestore}
            iconOnly
          />
        </div>
      </div>
      <PreviewableImageFrame src={url} alt={t(SLOT_LABEL_KEYS[slot])}>
        <AspectFrame ratio="16:9">
          <ImageFlipReveal
            key={path}
            src={url}
            alt={t(SLOT_LABEL_KEYS[slot])}
            className="h-full w-full object-contain"
            fallback={
              <div className="flex h-full w-full flex-col items-center justify-center gap-1 text-text-4">
                <ImagePlus className="h-6 w-6" />
                <span className="text-[10px]">{t("character_ref_empty")}</span>
              </div>
            }
          />
        </AspectFrame>
      </PreviewableImageFrame>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="focus-ring inline-flex items-center justify-center gap-1 rounded-md border border-hairline px-2 py-1 text-[11px] text-text-3"
        >
          <Upload className="h-3 w-3" />
          {t("common:upload")}
        </button>
        <GenerateButton
          onClick={() => onGenerateRef(characterName, formId, slot)}
          loading={generating}
          label={path ? t("regenerate_design") : t("generate_design")}
          className="justify-center text-[11px]"
        />
        <input
          ref={fileRef}
          type="file"
          accept=".png,.jpg,.jpeg,.webp"
          aria-label={t("common:upload")}
          className="hidden"
          onChange={(event) => void handleUpload(event).catch((err) => useAppStore.getState().pushToast(errMsg(err), "error"))}
        />
      </div>
    </div>
  );
}

function CapsLabel({
  children,
  htmlFor,
}: {
  children: React.ReactNode;
  htmlFor?: string;
}) {
  return (
    <label
      htmlFor={htmlFor}
      className="text-[10px] font-semibold uppercase tracking-[0.12em]"
      style={{ color: "var(--color-text-4)" }}
    >
      {children}
    </label>
  );
}
