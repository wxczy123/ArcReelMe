import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { UnitPreviewPanel } from "./UnitPreviewPanel";
import { useProjectsStore } from "@/stores/projects-store";
import type { ReferenceVideoUnit } from "@/types";

function mkUnit(overrides: Partial<ReferenceVideoUnit> = {}): ReferenceVideoUnit {
  return {
    unit_id: "E1U1",
    shots: [{ duration: 3, text: "Shot 1 (3s): x" }],
    references: [],
    duration_seconds: 3,
    duration_override: false,
    transition_to_next: "cut",
    note: null,
    generated_assets: {
      storyboard_image: null,
      storyboard_last_image: null,
      grid_id: null,
      grid_cell_index: null,
      video_clip: null,
      video_uri: null,
      status: "pending",
    },
    ...overrides,
  };
}

describe("UnitPreviewPanel", () => {
  it("shows placeholder when no unit is selected", () => {
    render(<UnitPreviewPanel unit={null} />);
    expect(screen.getByText(/Select a unit|选中左侧 Unit/)).toBeInTheDocument();
  });

  it("shows empty-video placeholder when unit has no video_clip", () => {
    render(<UnitPreviewPanel unit={mkUnit()} />);
    expect(screen.getByText(/Not yet generated|尚未生成/)).toBeInTheDocument();
  });

  it("renders <video> when video_clip is present", () => {
    useProjectsStore.setState({
      assetFingerprints: { "reference_videos/E1U1.mp4": 123 },
    });
    const unit = mkUnit({
      generated_assets: {
        ...mkUnit().generated_assets,
        status: "completed",
        video_clip: "reference_videos/E1U1.mp4",
      },
    });
    const { container } = render(
      <UnitPreviewPanel unit={unit} projectName="proj" />,
    );
    const video = container.querySelector("video");
    expect(video).toBeInTheDocument();
    expect(video?.getAttribute("src")).toContain("?v=123");
  });

  it("calls onUpload when a video file is selected", async () => {
    const onUpload = vi.fn();
    render(<UnitPreviewPanel unit={mkUnit()} onUpload={onUpload} />);
    const file = new File(["mp4"], "manual.mp4", { type: "video/mp4" });
    const input = screen
      .getAllByLabelText(/Upload video|上传视频/)
      .find((el): el is HTMLInputElement => el instanceof HTMLInputElement);
    expect(input).toBeDefined();
    fireEvent.change(input!, {
      target: { files: [file] },
    });
    await waitFor(() => {
      expect(onUpload).toHaveBeenCalledWith("E1U1", file);
    });
  });
});
