from lib.prompt_builders import (
    append_video_negative_tail,
    build_character_prompt,
    build_prop_prompt,
    build_scene_prompt,
    build_storyboard_suffix,
)


class TestCharacterPrompt:
    def test_includes_name_description_and_full_body_layout(self):
        prompt = build_character_prompt(
            "姜月茴",
            "黑发，冷静神态。",
            style="画风：古风",
            style_description="Cinematic, low-key lighting",
        )
        assert "姜月茴" in prompt
        assert "黑发，冷静神态。" in prompt
        assert "单人全身参考图" in prompt
        assert "从头到脚完整入画" in prompt
        assert "纯白色背景" in prompt
        assert "不要文字" in prompt
        # 风格前缀
        assert "画风：古风" in prompt
        assert "风格：画风" not in prompt
        assert "Cinematic, low-key lighting" in prompt

    def test_no_negative_prompt_field_returned(self):
        # build_character_prompt 仅返回字符串；资产图不再拼泛化负向尾巴
        prompt = build_character_prompt("张三", "短发青年")
        assert isinstance(prompt, str)
        assert "画面避免" not in prompt
        assert "水印" not in prompt
        assert "跨形态稳定外貌" not in prompt
        assert "当前形态" not in prompt


class TestScenePromptAndPropPrompt:
    def test_prop_three_views(self):
        prompt = build_prop_prompt("玉佩", "古朴温润", style="画风：写实")
        assert "玉佩" in prompt
        assert "古朴温润" in prompt
        assert "三视图" in prompt or "三个视图" in prompt
        assert "画风：写实" in prompt
        assert "风格：画风" not in prompt
        assert "画面避免" not in prompt

    def test_scene_prompt_is_single_scene_description(self):
        prompt = build_scene_prompt("祠堂", "昏暗古朴", style="画风：写实")
        assert "祠堂" in prompt
        assert "昏暗古朴" in prompt
        assert "画风：写实" in prompt
        assert "风格：画风" not in prompt
        assert "主画面" not in prompt
        assert "右下角" not in prompt
        assert "画面避免" not in prompt


class TestStoryboardSuffix:
    def test_by_aspect_ratio(self):
        assert build_storyboard_suffix(aspect_ratio="9:16") == "竖屏构图。"
        assert build_storyboard_suffix(aspect_ratio="16:9") == "横屏构图。"
        # 向后兼容：不传 aspect_ratio 时默认按 narration → 竖屏
        assert build_storyboard_suffix() == "竖屏构图。"


class TestVideoNegativeTail:
    def test_appends_when_missing(self):
        result = append_video_negative_tail("林清缓缓抬头")
        assert "林清缓缓抬头" in result
        assert "禁止出现：背景音乐、血迹、文字字幕、水印。" in result

    def test_idempotent(self):
        once = append_video_negative_tail("林清缓缓抬头")
        twice = append_video_negative_tail(once)
        assert once == twice

    def test_handles_empty_input(self):
        result = append_video_negative_tail("")
        assert "禁止出现：背景音乐、血迹、文字字幕、水印。" in result

    def test_handles_whitespace_only_input(self):
        # 纯空白等同空：避免拼出前导空行 + 尾词的怪异输出
        for blank in ("   ", "\n\n", "\t \n"):
            result = append_video_negative_tail(blank)
            assert result.startswith("禁止出现"), f"input={blank!r} → {result!r}"
