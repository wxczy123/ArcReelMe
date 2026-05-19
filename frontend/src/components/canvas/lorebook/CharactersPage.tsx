import { useState } from "react";
import { useTranslation } from "react-i18next";
import { User } from "lucide-react";
import { GalleryToolbar } from "./GalleryToolbar";
import { CharacterCard } from "./CharacterCard";
import { AssetFormModal } from "@/components/assets/AssetFormModal";
import { AssetPickerModal } from "@/components/assets/AssetPickerModal";
import { API } from "@/api";
import { useAppStore } from "@/stores/app-store";
import { useScrollTarget } from "@/hooks/useScrollTarget";
import { errMsg } from "@/utils/async";
import type { Character, CharacterRefSlot } from "@/types";
import { GalleryEmptyState } from "./GalleryEmptyState";

interface Props {
  projectName: string;
  characters: Record<string, Character>;
  onSaveCharacter: (name: string, payload: { description: string; voiceStyle: string }) => Promise<void>;
  onGenerateCharacterRef: (name: string, formId: string, slot: CharacterRefSlot) => void;
  onAddCharacter: (name: string, description: string, voiceStyle: string, referenceFile?: File | null) => Promise<void>;
  onAddCharacterForm: (name: string, formId: string, label: string, description: string) => Promise<void>;
  onUpdateCharacterForm: (name: string, formId: string, updates: {
    label?: string;
    description?: string;
    storyboard_ref_slot?: CharacterRefSlot;
    default_form?: boolean;
  }) => Promise<void>;
  onDeleteCharacterForm: (name: string, formId: string) => Promise<void>;
  onUploadCharacterFormRef: (name: string, formId: string, slot: CharacterRefSlot, file: File) => Promise<void>;
  onUploadCharacterInputRef: (name: string, formId: string, file: File) => Promise<void>;
  onDeleteCharacterInputRef: (name: string, formId: string, path: string) => Promise<void>;
  onRestoreCharacterVersion?: () => Promise<void> | void;
  onRefreshProject?: () => Promise<void> | void;
  generatingCharacterRefKeys?: Set<string>;
}

export function CharactersPage({
  projectName,
  characters,
  onSaveCharacter,
  onGenerateCharacterRef,
  onAddCharacter,
  onAddCharacterForm,
  onUpdateCharacterForm,
  onDeleteCharacterForm,
  onUploadCharacterFormRef,
  onUploadCharacterInputRef,
  onDeleteCharacterInputRef,
  onRefreshProject,
  generatingCharacterRefKeys,
}: Props) {
  const { t } = useTranslation(["dashboard", "assets"]);
  const [adding, setAdding] = useState(false);
  const [picking, setPicking] = useState(false);

  useScrollTarget("character");

  const entries = Object.entries(characters);

  const handleImport = async (ids: string[]) => {
    try {
      await API.applyAssetsToProject({
        asset_ids: ids,
        target_project: projectName,
        conflict_policy: "skip",
      });
      useAppStore.getState().pushToast(t("assets:import_count", { count: ids.length }), "success");
      await onRefreshProject?.();
    } catch (err) {
      useAppStore.getState().pushToast(errMsg(err), "error");
    } finally {
      setPicking(false);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <GalleryToolbar
        title={t("dashboard:characters")}
        count={entries.length}
        onAdd={() => setAdding(true)}
        onPickFromLibrary={() => setPicking(true)}
      />
      <div className="px-5 py-5">
        {entries.length === 0 ? (
          <GalleryEmptyState
            icon={<User className="h-6 w-6" />}
            label={t("dashboard:characters")}
            hint={t("dashboard:no_characters_hint_clickable")}
            onClick={() => setAdding(true)}
          />
        ) : (
          <div className="grid justify-evenly gap-4 [grid-template-columns:repeat(auto-fill,320px)]">
            {entries.map(([name, char]) => (
              <CharacterCard key={name} name={name} character={char} projectName={projectName}
                onSave={onSaveCharacter}
                onGenerateRef={onGenerateCharacterRef}
                onAddForm={onAddCharacterForm}
                onUpdateForm={onUpdateCharacterForm}
                onDeleteForm={onDeleteCharacterForm}
                onUploadFormRef={onUploadCharacterFormRef}
                onUploadInputRef={onUploadCharacterInputRef}
                onDeleteInputRef={onDeleteCharacterInputRef}
                onReload={onRefreshProject}
                generatingRefKeys={generatingCharacterRefKeys}
              />
            ))}
          </div>
        )}
      </div>

      {adding && (
        <AssetFormModal
          type="character"
          mode="create"
          onClose={() => setAdding(false)}
          onSubmit={async ({ name, description, voice_style, image }) => {
            await onAddCharacter(name, description, voice_style, image ?? null);
            setAdding(false);
          }}
        />
      )}

      {picking && (
        <AssetPickerModal
          type="character"
          existingNames={new Set(Object.keys(characters))}
          onClose={() => setPicking(false)}
          onImport={(ids) => { void handleImport(ids); }}
        />
      )}
    </div>
  );
}
