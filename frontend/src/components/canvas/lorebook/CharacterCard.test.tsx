import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CharacterCard } from "./CharacterCard";
import { useAppStore } from "@/stores/app-store";

vi.mock("@/components/canvas/timeline/VersionTimeMachine", () => ({
  VersionTimeMachine: (props: { resourceType: string; resourceId: string }) => (
    <div data-testid="version-time-machine" data-resource-type={props.resourceType} data-resource-id={props.resourceId}>
      versions
    </div>
  ),
}));

describe("CharacterCard", () => {
  beforeEach(() => {
    useAppStore.setState(useAppStore.getInitialState(), true);
    vi.restoreAllMocks();
    Object.defineProperty(globalThis.URL, "createObjectURL", {
      writable: true,
      value: vi.fn(() => "blob:character-ref"),
    });
    Object.defineProperty(globalThis.URL, "revokeObjectURL", {
      writable: true,
      value: vi.fn(),
    });
  });

  it("renders the active full-body storyboard reference image", () => {
    render(
      <CharacterCard
        name="Hero"
        character={{
          description: "hero desc",
          voice_style: "warm",
          default_form: "default",
          forms: {
            default: {
              label: "默认造型",
              description: "hero desc",
              storyboard_ref_slot: "full_body",
              input_refs: [],
              refs: {
                full_body: {
                  path: "characters/Hero/default/full_body.png",
                  purpose: "storyboard_reference",
                },
                three_view: {
                  path: "",
                  purpose: "consistency_review",
                },
              },
            },
          },
        }}
        projectName="demo"
        onSave={vi.fn()}
        onGenerateRef={vi.fn()}
      />,
    );

    expect(screen.getByAltText(/Hero.*当前分镜参考图/)).toHaveAttribute(
      "src",
      "/api/v1/files/demo/characters/Hero/default/full_body.png",
    );
  });

  it("saves edited base character description and voice style", async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <CharacterCard
        name="Hero"
        character={{ description: "hero desc", voice_style: "warm" }}
        projectName="demo"
        onSave={onSave}
        onGenerateRef={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText(/角色描述/), {
      target: { value: "new hero desc" },
    });
    fireEvent.change(screen.getByPlaceholderText(/温柔但有威严/), {
      target: { value: "clear voice" },
    });

    fireEvent.click(screen.getByRole("button", { name: /保存/ }));

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith("Hero", {
        description: "new hero desc",
        voiceStyle: "clear voice",
      });
    });
  });

  it("uploads input refs and generates a selected reference slot", async () => {
    const onUploadInputRef = vi.fn().mockResolvedValue(undefined);
    const onGenerateRef = vi.fn();
    render(
      <CharacterCard
        name="Hero"
        character={{ description: "hero desc", voice_style: "warm" }}
        projectName="demo"
        onSave={vi.fn().mockResolvedValue(undefined)}
        onGenerateRef={onGenerateRef}
        onUploadInputRef={onUploadInputRef}
      />,
    );

    const file = new File(["ref"], "hero.png", { type: "image/png" });
    fireEvent.change(screen.getByLabelText("上传全身图参考"), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(onUploadInputRef).toHaveBeenCalledWith("Hero", "default", file);
    });

    fireEvent.click(screen.getAllByRole("button", { name: /生成设计图/ })[0]);

    expect(onGenerateRef).toHaveBeenCalledWith("Hero", "default", "full_body");
  });

  it("deletes input refs and exposes character ref version entries", async () => {
    const onDeleteInputRef = vi.fn().mockResolvedValue(undefined);
    render(
      <CharacterCard
        name="Hero"
        character={{
          description: "hero desc",
          voice_style: "warm",
          default_form: "default",
          forms: {
            default: {
              label: "默认造型",
              description: "hero desc",
              storyboard_ref_slot: "full_body",
              input_refs: ["characters/Hero/default/input_refs/style.png"],
              refs: {
                full_body: {
                  path: "characters/Hero/default/full_body.png",
                  purpose: "storyboard_reference",
                },
                three_view: {
                  path: "characters/Hero/default/three_view.png",
                  purpose: "consistency_review",
                },
              },
            },
          },
        }}
        projectName="demo"
        onSave={vi.fn().mockResolvedValue(undefined)}
        onGenerateRef={vi.fn()}
        onDeleteInputRef={onDeleteInputRef}
      />,
    );

    const versionEntries = screen.getAllByTestId("version-time-machine");
    expect(versionEntries).toHaveLength(2);
    expect(versionEntries[0]).toHaveAttribute("data-resource-type", "character_refs");
    expect(versionEntries[0]).toHaveAttribute("data-resource-id", "Hero/default/full_body");
    expect(versionEntries[1]).toHaveAttribute("data-resource-id", "Hero/default/three_view");

    fireEvent.click(screen.getByRole("button", { name: "删除全身图参考" }));

    await waitFor(() => {
      expect(onDeleteInputRef).toHaveBeenCalledWith(
        "Hero",
        "default",
        "characters/Hero/default/input_refs/style.png",
      );
    });
  });
});
