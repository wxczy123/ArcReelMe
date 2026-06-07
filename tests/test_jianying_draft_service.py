"""剪映草稿导出服务的单元测试"""

import json
import zipfile

import pytest


class TestCollectVideoClips:
    """测试从剧本中收集已完成视频片段"""

    def test_narration_mode_collects_existing_videos(self, tmp_path):
        """narration 模式：收集存在的 video_clip"""
        from server.services.jianying_draft_service import JianyingDraftService

        project_dir = tmp_path / "projects" / "demo"
        videos_dir = project_dir / "videos"
        videos_dir.mkdir(parents=True)
        (videos_dir / "segment_S1.mp4").write_bytes(b"fake")
        (videos_dir / "segment_S2.mp4").write_bytes(b"fake")

        script = {
            "content_mode": "narration",
            "segments": [
                {
                    "segment_id": "S1",
                    "duration_seconds": 8,
                    "novel_text": "从前有座山",
                    "generated_assets": {"video_clip": "videos/segment_S1.mp4", "status": "completed"},
                },
                {
                    "segment_id": "S2",
                    "duration_seconds": 6,
                    "novel_text": "山上有座庙",
                    "generated_assets": {"video_clip": "videos/segment_S2.mp4", "status": "completed"},
                },
                {
                    "segment_id": "S3",
                    "duration_seconds": 8,
                    "novel_text": "庙里有个老和尚",
                    "generated_assets": {"status": "pending"},
                },
            ],
        }

        svc = JianyingDraftService.__new__(JianyingDraftService)
        clips = svc._collect_video_clips(script, project_dir)

        assert len(clips) == 2
        assert clips[0]["id"] == "S1"
        assert clips[0]["novel_text"] == "从前有座山"
        assert clips[1]["id"] == "S2"

    def test_drama_mode_collects_scenes(self, tmp_path):
        """drama 模式：收集 scenes 而非 segments"""
        from server.services.jianying_draft_service import JianyingDraftService

        project_dir = tmp_path / "projects" / "demo"
        videos_dir = project_dir / "videos"
        videos_dir.mkdir(parents=True)
        (videos_dir / "scene_E1S01.mp4").write_bytes(b"fake")

        script = {
            "content_mode": "drama",
            "scenes": [
                {
                    "scene_id": "E1S01",
                    "duration_seconds": 8,
                    "generated_assets": {"video_clip": "videos/scene_E1S01.mp4", "status": "completed"},
                },
            ],
        }

        svc = JianyingDraftService.__new__(JianyingDraftService)
        clips = svc._collect_video_clips(script, project_dir)

        assert len(clips) == 1
        assert clips[0]["id"] == "E1S01"
        assert clips[0]["novel_text"] == ""

    def test_reference_video_mode_collects_video_units(self, tmp_path):
        """reference_video 模式：收集 video_units 中的 reference_videos。"""
        from server.services.jianying_draft_service import JianyingDraftService

        project_dir = tmp_path / "projects" / "demo"
        video_dir = project_dir / "reference_videos"
        video_dir.mkdir(parents=True)
        (video_dir / "E1U01.mp4").write_bytes(b"fake")

        script = {
            "content_mode": "drama",
            "generation_mode": "reference_video",
            "scenes": [],
            "video_units": [
                {
                    "unit_id": "E1U01",
                    "duration_seconds": 10,
                    "transition_to_next": "fade",
                    "generated_assets": {
                        "video_clip": "reference_videos/E1U01.mp4",
                        "status": "completed",
                    },
                },
                {
                    "unit_id": "E1U02",
                    "duration_seconds": 8,
                    "generated_assets": {"status": "pending"},
                },
            ],
        }

        svc = JianyingDraftService.__new__(JianyingDraftService)
        clips = svc._collect_video_clips(script, project_dir)

        assert len(clips) == 1
        assert clips[0]["id"] == "E1U01"
        assert clips[0]["video_clip"] == "reference_videos/E1U01.mp4"
        assert clips[0]["duration_seconds"] == 10
        assert clips[0]["transition_to_next"] == "fade"

    def test_skips_missing_video_files(self, tmp_path):
        """script 中有记录但文件不存在时跳过"""
        from server.services.jianying_draft_service import JianyingDraftService

        project_dir = tmp_path / "projects" / "demo"
        project_dir.mkdir(parents=True)

        script = {
            "content_mode": "narration",
            "segments": [
                {
                    "segment_id": "S1",
                    "duration_seconds": 8,
                    "novel_text": "text",
                    "generated_assets": {"video_clip": "videos/segment_S1.mp4", "status": "completed"},
                },
            ],
        }

        svc = JianyingDraftService.__new__(JianyingDraftService)
        clips = svc._collect_video_clips(script, project_dir)

        assert len(clips) == 0


class TestResolveCanvasSize:
    """测试画布尺寸解析"""

    def test_16_9_returns_1920x1080(self):
        from server.services.jianying_draft_service import JianyingDraftService

        svc = JianyingDraftService.__new__(JianyingDraftService)
        w, h = svc._resolve_canvas_size({"aspect_ratio": {"video": "16:9"}})
        assert (w, h) == (1920, 1080)

    def test_9_16_returns_1080x1920(self):
        from server.services.jianying_draft_service import JianyingDraftService

        svc = JianyingDraftService.__new__(JianyingDraftService)
        w, h = svc._resolve_canvas_size({"aspect_ratio": {"video": "9:16"}})
        assert (w, h) == (1080, 1920)

    def test_default_is_16_9(self):
        from server.services.jianying_draft_service import JianyingDraftService

        svc = JianyingDraftService.__new__(JianyingDraftService)
        w, h = svc._resolve_canvas_size({})
        assert (w, h) == (1920, 1080)


from tests.conftest import make_test_video


class TestGenerateDraft:
    """测试 pyjianyingdraft 草稿生成"""

    def test_generates_draft_content_json(self, tmp_path):
        """生成的草稿目录包含 draft_content.json"""
        from server.services.jianying_draft_service import JianyingDraftService

        # 视频文件放在 draft_dir 外部，避免被 create_draft 清理
        videos_dir = tmp_path / "videos"
        videos_dir.mkdir()
        make_test_video(videos_dir / "scene_S1.mp4")
        make_test_video(videos_dir / "scene_S2.mp4")

        draft_dir = tmp_path / "drafts" / "测试草稿"

        clips = [
            {"id": "S1", "local_path": str(videos_dir / "scene_S1.mp4"), "novel_text": ""},
            {"id": "S2", "local_path": str(videos_dir / "scene_S2.mp4"), "novel_text": ""},
        ]

        svc = JianyingDraftService.__new__(JianyingDraftService)
        svc._generate_draft(
            draft_dir=draft_dir,
            draft_name="测试草稿",
            clips=clips,
            width=1920,
            height=1080,
            content_mode="drama",
        )

        assert (draft_dir / "draft_content.json").exists()
        assert (draft_dir / "draft_meta_info.json").exists()

    def test_narration_mode_includes_subtitle_track(self, tmp_path):
        """narration 模式生成字幕轨"""
        from server.services.jianying_draft_service import JianyingDraftService

        videos_dir = tmp_path / "videos"
        videos_dir.mkdir()
        make_test_video(videos_dir / "seg_S1.mp4")

        draft_dir = tmp_path / "drafts" / "字幕草稿"

        clips = [
            {"id": "S1", "local_path": str(videos_dir / "seg_S1.mp4"), "novel_text": "从前有座山"},
        ]

        svc = JianyingDraftService.__new__(JianyingDraftService)
        svc._generate_draft(
            draft_dir=draft_dir,
            draft_name="字幕草稿",
            clips=clips,
            width=1080,
            height=1920,
            content_mode="narration",
        )

        content = json.loads((draft_dir / "draft_content.json").read_text(encoding="utf-8"))
        tracks = content.get("tracks", [])
        assert len(tracks) == 2

    def test_drama_mode_no_subtitle_track(self, tmp_path):
        """drama 模式不生成字幕轨"""
        from server.services.jianying_draft_service import JianyingDraftService

        videos_dir = tmp_path / "videos"
        videos_dir.mkdir()
        make_test_video(videos_dir / "scene_S1.mp4")

        draft_dir = tmp_path / "drafts" / "无字幕草稿"

        clips = [
            {"id": "S1", "local_path": str(videos_dir / "scene_S1.mp4"), "novel_text": ""},
        ]

        svc = JianyingDraftService.__new__(JianyingDraftService)
        svc._generate_draft(
            draft_dir=draft_dir,
            draft_name="无字幕草稿",
            clips=clips,
            width=1920,
            height=1080,
            content_mode="drama",
        )

        content = json.loads((draft_dir / "draft_content.json").read_text(encoding="utf-8"))
        tracks = content.get("tracks", [])
        assert len(tracks) == 1


class TestTransitions:
    """测试 transition_to_next 字段在剪映草稿中的实际接入"""

    def _generate_with_transitions(self, tmp_path, transitions: list[str]) -> dict:
        from server.services.jianying_draft_service import JianyingDraftService

        videos_dir = tmp_path / "videos"
        videos_dir.mkdir()
        clips = []
        for i, t in enumerate(transitions):
            path = videos_dir / f"scene_S{i + 1}.mp4"
            make_test_video(path)
            clips.append({"id": f"S{i + 1}", "local_path": str(path), "novel_text": "", "transition_to_next": t})

        draft_dir = tmp_path / "drafts" / "转场草稿"
        svc = JianyingDraftService.__new__(JianyingDraftService)
        svc._generate_draft(
            draft_dir=draft_dir,
            draft_name="转场草稿",
            clips=clips,
            width=1920,
            height=1080,
            content_mode="drama",
        )
        return json.loads((draft_dir / "draft_content.json").read_text(encoding="utf-8"))

    def test_cut_does_not_attach_transition(self, tmp_path):
        content = self._generate_with_transitions(tmp_path, ["cut", "cut"])
        assert content.get("materials", {}).get("transitions", []) == []

    def test_fade_attaches_transition_material(self, tmp_path):
        content = self._generate_with_transitions(tmp_path, ["fade", "cut"])
        transitions = content.get("materials", {}).get("transitions", [])
        assert len(transitions) == 1
        # 闪黑 在 transition_meta 中的 effect_id
        assert transitions[0].get("effect_id") == "321493"

    def test_dissolve_attaches_transition_material(self, tmp_path):
        content = self._generate_with_transitions(tmp_path, ["dissolve", "cut"])
        transitions = content.get("materials", {}).get("transitions", [])
        assert len(transitions) == 1
        # 叠化 effect_id
        assert transitions[0].get("effect_id") == "322577"

    def test_last_segment_transition_ignored(self, tmp_path):
        # 最后一段即使字段非 cut 也不能挂（剪映约定挂在前段）
        content = self._generate_with_transitions(tmp_path, ["cut", "fade"])
        assert content.get("materials", {}).get("transitions", []) == []

    def test_collect_video_clips_includes_transition_field(self, tmp_path):
        from server.services.jianying_draft_service import JianyingDraftService

        project_dir = tmp_path / "projects" / "demo"
        videos_dir = project_dir / "videos"
        videos_dir.mkdir(parents=True)
        (videos_dir / "scene_E1S01.mp4").write_bytes(b"fake")

        script = {
            "content_mode": "drama",
            "scenes": [
                {
                    "scene_id": "E1S01",
                    "duration_seconds": 6,
                    "transition_to_next": "fade",
                    "generated_assets": {"video_clip": "videos/scene_E1S01.mp4", "status": "completed"},
                },
            ],
        }
        svc = JianyingDraftService.__new__(JianyingDraftService)
        clips = svc._collect_video_clips(script, project_dir)
        assert clips[0]["transition_to_next"] == "fade"


class TestReplacePaths:
    """测试路径后处理（JSON 安全替换）"""

    def test_replaces_tmp_prefix_in_json(self, tmp_path):
        """递归替换 JSON 中的临时路径前缀"""
        from server.services.jianying_draft_service import JianyingDraftService

        json_path = tmp_path / "draft_content.json"
        data = {
            "materials": {
                "videos": [
                    {"path": "/tmp/arcreel_jy_abc/草稿/assets/s1.mp4"},
                    {"path": "/tmp/arcreel_jy_abc/草稿/assets/s2.mp4"},
                ]
            },
            "other": "no change",
        }
        json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        svc = JianyingDraftService.__new__(JianyingDraftService)
        svc._replace_paths_in_draft(
            json_path=json_path,
            tmp_prefix="/tmp/arcreel_jy_abc/草稿/assets",
            target_prefix="/Users/test/Movies/JianyingPro/草稿/assets",
        )

        result = json.loads(json_path.read_text(encoding="utf-8"))
        assert result["materials"]["videos"][0]["path"] == "/Users/test/Movies/JianyingPro/草稿/assets/s1.mp4"
        assert result["materials"]["videos"][1]["path"] == "/Users/test/Movies/JianyingPro/草稿/assets/s2.mp4"
        assert result["other"] == "no change"


class TestExportEpisodeDraft:
    """端到端测试：完整导出流程"""

    def _setup_project(self, tmp_path) -> tuple:
        """创建带视频片段的测试项目"""
        from lib.project_manager import ProjectManager

        pm = ProjectManager(tmp_path / "projects")
        project_dir = tmp_path / "projects" / "demo"
        project_dir.mkdir(parents=True)
        videos_dir = project_dir / "videos"
        videos_dir.mkdir()

        make_test_video(videos_dir / "segment_S1.mp4")
        make_test_video(videos_dir / "segment_S2.mp4")

        project_data = {
            "title": "测试项目",
            "content_mode": "narration",
            "aspect_ratio": {"video": "9:16"},
            "episodes": [
                {"episode": 1, "title": "第一集", "script_file": "scripts/episode_1.json"},
            ],
        }
        (project_dir / "project.json").write_text(json.dumps(project_data, ensure_ascii=False), encoding="utf-8")

        scripts_dir = project_dir / "scripts"
        scripts_dir.mkdir()
        script_data = {
            "content_mode": "narration",
            "segments": [
                {
                    "segment_id": "S1",
                    "duration_seconds": 8,
                    "novel_text": "从前有座山",
                    "generated_assets": {"video_clip": "videos/segment_S1.mp4", "status": "completed"},
                },
                {
                    "segment_id": "S2",
                    "duration_seconds": 6,
                    "novel_text": "山上有座庙",
                    "generated_assets": {"video_clip": "videos/segment_S2.mp4", "status": "completed"},
                },
            ],
        }
        (scripts_dir / "episode_1.json").write_text(json.dumps(script_data, ensure_ascii=False), encoding="utf-8")

        return pm, project_dir

    def test_exports_zip_with_correct_structure(self, tmp_path):
        """导出 ZIP 包含草稿 JSON + 视频素材"""
        from server.services.jianying_draft_service import JianyingDraftService

        pm, _ = self._setup_project(tmp_path)
        svc = JianyingDraftService(pm)

        zip_path = svc.export_episode_draft(
            project_name="demo",
            episode=1,
            draft_path="/Users/test/Movies/JianyingPro/User Data/Projects/com.lveditor.draft",
        )

        assert zip_path.exists()
        assert zip_path.suffix == ".zip"

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            assert any("draft_content.json" in n for n in names)
            assert any("draft_info.json" in n for n in names)
            assert any("draft_meta_info.json" in n for n in names)
            assert any("segment_S1.mp4" in n for n in names)
            assert any("segment_S2.mp4" in n for n in names)

    def test_exports_zip_with_scannable_draft_metadata(self, tmp_path):
        """导出 ZIP 补齐剪映草稿列表扫描需要的元信息"""
        from server.services.jianying_draft_service import JianyingDraftService

        pm, _ = self._setup_project(tmp_path)
        svc = JianyingDraftService(pm)
        draft_path = r"C:\Users\test\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft"

        zip_path = svc.export_episode_draft(project_name="demo", episode=1, draft_path=draft_path)

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            content_entry = [n for n in names if n.endswith("draft_content.json")][0]
            info_entry = [n for n in names if n.endswith("draft_info.json")][0]
            meta_entry = [n for n in names if n.endswith("draft_meta_info.json")][0]
            content = json.loads(zf.read(content_entry).decode("utf-8"))
            info = json.loads(zf.read(info_entry).decode("utf-8"))
            meta = json.loads(zf.read(meta_entry).decode("utf-8"))

            assert content["name"] == "测试项目_第1集"
            assert content["id"]
            assert content["create_time"] > 0
            assert content["update_time"] > 0
            assert info["id"] == content["id"]
            assert info["name"] == content["name"]
            assert meta["draft_id"] == content["id"]
            assert meta["draft_name"] == content["name"]
            assert meta["draft_fold_path"] == draft_path.replace("\\", "/")
            assert meta["draft_root_path"] == f"{draft_path.replace('\\', '/')}/测试项目_第1集"
            video_paths = [video["path"] for video in content["materials"]["videos"]]
            assert all(path.startswith(f"{draft_path.replace('\\', '/')}/测试项目_第1集/assets/") for path in video_paths)
            assert all("\\" not in path for path in video_paths)
            video_materials = next(item for item in meta["draft_materials"] if item["type"] == 0)["value"]
            assert len(video_materials) == len(content["materials"]["videos"])
            assert {item["file_Path"] for item in video_materials} == set(video_paths)
            assert {item["id"] for item in video_materials} == {
                video["id"] for video in content["materials"]["videos"]
            }

    def test_exports_multiple_episodes_as_one_combined_draft(self, tmp_path):
        """批量导出时，一个 ZIP 内包含一个合并后的剪映草稿目录"""
        from server.services.jianying_draft_service import JianyingDraftService

        pm, project_dir = self._setup_project(tmp_path)
        videos_dir = project_dir / "videos"
        make_test_video(videos_dir / "segment_E2S1.mp4")
        scripts_dir = project_dir / "scripts"
        project_data = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
        project_data["episodes"].append({"episode": 2, "title": "第二集", "script_file": "scripts/episode_2.json"})
        (project_dir / "project.json").write_text(json.dumps(project_data, ensure_ascii=False), encoding="utf-8")
        (scripts_dir / "episode_2.json").write_text(
            json.dumps(
                {
                    "content_mode": "narration",
                    "segments": [
                        {
                            "segment_id": "S1",
                            "duration_seconds": 8,
                            "novel_text": "第二集文本",
                            "generated_assets": {"video_clip": "videos/segment_E2S1.mp4", "status": "completed"},
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        svc = JianyingDraftService(pm)
        draft_path = r"C:\Users\test\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft"
        zip_path = svc.export_episodes_drafts(
            project_name="demo",
            episodes=[1, 2],
            draft_path=draft_path,
        )

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            roots = {name.split("/")[0] for name in names}
            assert roots == {"测试项目"}
            assert "测试项目/draft_content.json" in names
            assert "测试项目/draft_meta_info.json" in names
            assert "测试项目/draft_info.json" in names
            assert "测试项目/assets/segment_S1.mp4" in names
            assert "测试项目/assets/segment_S2.mp4" in names
            assert "测试项目/assets/segment_E2S1.mp4" in names

            content = json.loads(zf.read("测试项目/draft_content.json").decode("utf-8"))
            info = json.loads(zf.read("测试项目/draft_info.json").decode("utf-8"))
            meta = json.loads(zf.read("测试项目/draft_meta_info.json").decode("utf-8"))
            videos = content["materials"]["videos"]
            segments = content["tracks"][0]["segments"]
            video_materials = next(item for item in meta["draft_materials"] if item["type"] == 0)["value"]
            assert content["name"] == "测试项目"
            assert info["id"] == content["id"]
            assert meta["draft_id"] == content["id"]
            assert meta["draft_name"] == "测试项目"
            assert meta["draft_fold_path"] == draft_path.replace("\\", "/")
            assert meta["draft_root_path"] == f"{draft_path.replace('\\', '/')}/测试项目"
            assert len(videos) == 3
            assert len(video_materials) == 3
            assert {item["file_Path"] for item in video_materials} == {video["path"] for video in videos}
            assert all(video["path"].startswith(f"{draft_path.replace('\\', '/')}/测试项目/assets/") for video in videos)
            assert all("\\" not in video["path"] for video in videos)
            assert [segment["target_timerange"]["start"] for segment in segments] == [
                0,
                segments[0]["target_timerange"]["duration"],
                segments[0]["target_timerange"]["duration"] + segments[1]["target_timerange"]["duration"],
            ]
            assert content["duration"] == sum(segment["target_timerange"]["duration"] for segment in segments)
            assert zf.testzip() is None

    def test_exports_multiple_episodes_as_separate_drafts_when_requested(self, tmp_path):
        """批量导出可选择每集保持独立剪映草稿目录"""
        from server.services.jianying_draft_service import JianyingDraftService

        pm, project_dir = self._setup_project(tmp_path)
        videos_dir = project_dir / "videos"
        make_test_video(videos_dir / "segment_E2S1.mp4")
        scripts_dir = project_dir / "scripts"
        project_data = json.loads((project_dir / "project.json").read_text(encoding="utf-8"))
        project_data["episodes"].append({"episode": 2, "title": "第二集", "script_file": "scripts/episode_2.json"})
        (project_dir / "project.json").write_text(json.dumps(project_data, ensure_ascii=False), encoding="utf-8")
        (scripts_dir / "episode_2.json").write_text(
            json.dumps(
                {
                    "content_mode": "narration",
                    "segments": [
                        {
                            "segment_id": "S1",
                            "duration_seconds": 8,
                            "novel_text": "第二集文本",
                            "generated_assets": {"video_clip": "videos/segment_E2S1.mp4", "status": "completed"},
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        svc = JianyingDraftService(pm)
        zip_path = svc.export_episodes_drafts(
            project_name="demo",
            episodes=[1, 2],
            draft_path=r"C:\Users\test\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft",
            combine=False,
        )

        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            roots = {name.split("/")[0] for name in names}
            assert roots == {"测试项目_第1集", "测试项目_第2集"}
            assert "测试项目_第1集/draft_content.json" in names
            assert "测试项目_第1集/draft_meta_info.json" in names
            assert "测试项目_第1集/draft_info.json" in names
            assert "测试项目_第1集/assets/segment_S1.mp4" in names
            assert "测试项目_第1集/assets/segment_S2.mp4" in names
            assert "测试项目_第2集/draft_content.json" in names
            assert "测试项目_第2集/draft_meta_info.json" in names
            assert "测试项目_第2集/draft_info.json" in names
            assert "测试项目_第2集/assets/segment_E2S1.mp4" in names

            ep1_content = json.loads(zf.read("测试项目_第1集/draft_content.json").decode("utf-8"))
            ep1_meta = json.loads(zf.read("测试项目_第1集/draft_meta_info.json").decode("utf-8"))
            ep2_content = json.loads(zf.read("测试项目_第2集/draft_content.json").decode("utf-8"))
            ep2_meta = json.loads(zf.read("测试项目_第2集/draft_meta_info.json").decode("utf-8"))
            assert ep1_content["name"] == "测试项目_第1集"
            assert ep1_meta["draft_name"] == "测试项目_第1集"
            assert ep2_content["name"] == "测试项目_第2集"
            assert ep2_meta["draft_name"] == "测试项目_第2集"
            assert len(next(item for item in ep1_meta["draft_materials"] if item["type"] == 0)["value"]) == 2
            assert len(next(item for item in ep2_meta["draft_materials"] if item["type"] == 0)["value"]) == 1
            assert zf.testzip() is None

    def test_draft_content_has_user_paths(self, tmp_path):
        """draft_info.json 中的路径已替换为用户本地路径"""
        from server.services.jianying_draft_service import JianyingDraftService

        pm, _ = self._setup_project(tmp_path)
        svc = JianyingDraftService(pm)
        draft_path = "/Users/test/drafts"

        zip_path = svc.export_episode_draft(project_name="demo", episode=1, draft_path=draft_path)

        with zipfile.ZipFile(zip_path) as zf:
            content_entry = [n for n in zf.namelist() if "draft_info.json" in n][0]
            content = json.loads(zf.read(content_entry).decode("utf-8"))
            raw = json.dumps(content)
            assert "/tmp/" not in raw and "\\Temp\\" not in raw
            assert draft_path in raw

    def test_episode_not_found_raises(self, tmp_path):
        """集数不存在时抛出 FileNotFoundError"""
        from server.services.jianying_draft_service import JianyingDraftService

        pm, _ = self._setup_project(tmp_path)
        svc = JianyingDraftService(pm)

        with pytest.raises(FileNotFoundError, match="第 99 集不存在"):
            svc.export_episode_draft(project_name="demo", episode=99, draft_path="/tmp")

    def test_no_videos_raises_value_error(self, tmp_path):
        """无已完成视频时抛出 ValueError"""
        from lib.project_manager import ProjectManager
        from server.services.jianying_draft_service import JianyingDraftService

        pm = ProjectManager(tmp_path / "projects")
        project_dir = tmp_path / "projects" / "empty"
        project_dir.mkdir(parents=True)

        (project_dir / "project.json").write_text(
            json.dumps(
                {
                    "title": "空项目",
                    "content_mode": "narration",
                    "episodes": [{"episode": 1, "title": "第一集", "script_file": "scripts/episode_1.json"}],
                },
                ensure_ascii=False,
            )
        )

        scripts_dir = project_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "episode_1.json").write_text(
            json.dumps(
                {
                    "content_mode": "narration",
                    "segments": [
                        {
                            "segment_id": "S1",
                            "duration_seconds": 8,
                            "novel_text": "",
                            "generated_assets": {"status": "pending"},
                        },
                    ],
                },
                ensure_ascii=False,
            )
        )

        svc = JianyingDraftService(pm)
        with pytest.raises(ValueError, match="请先生成视频"):
            svc.export_episode_draft(project_name="empty", episode=1, draft_path="/tmp")
