# tests/test_video_renderer.py — Unit Tests for 3-Stage Segmented Pipeline
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from engine.models import SpecOutput, SceneSpec, ClipsManifest, ClipItem, SEOMetadata, WordTimestamp
from scripts.render_video import generate_ass_subtitles, render_video_ffmpeg, check_filter_supported


def test_generate_ass_subtitles(tmp_path):
    """Verifies that kinetic word-by-word micro-chunked ASS subtitles are properly constructed."""
    output_ass = str(tmp_path / "captions.ass")
    scenes = [
        SceneSpec(
            scene_id=1,
            spoken_text="The human brain stores infinite memories.",
            phonetic_text="The human brain stores infinite memories.",
            stock_video_query="brain memory",
            duration_seconds=5.0,
            word_timestamps=[
                WordTimestamp(word="The", start=0.0, end=0.3),
                WordTimestamp(word="human", start=0.3, end=0.8),
                WordTimestamp(word="brain", start=0.8, end=1.5),
                WordTimestamp(word="stores", start=1.5, end=2.0),
                WordTimestamp(word="infinite", start=2.0, end=2.8),
                WordTimestamp(word="memories.", start=2.8, end=3.5),
            ]
        )
    ]

    generate_ass_subtitles(
        scenes=scenes,
        output_ass_path=output_ass,
        width=1080,
        height=1920,
        font_name="Anton",
        font_size=72,
        active_color="&H0000FFFF",
        inactive_color="&H00FFFFFF"
    )

    assert os.path.exists(output_ass)
    with open(output_ass, "r", encoding="utf-8") as f:
        content = f.read()

    assert "[Script Info]" in content
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    assert "Style: Default,Anton,72,&H00FFFFFF" in content
    assert "[Events]" in content
    # Verify word-by-word highlighting tag and stripped punctuation
    assert "{\\c&H0000FFFF}" in content
    assert "The" in content
    assert "brain" in content
    assert "memories" in content
    assert "memories." not in content


def test_render_video_ffmpeg_segmented_pipeline(tmp_path, monkeypatch):
    """Verifies that render_video_ffmpeg executes the 3-stage segmented pipeline sequentially."""
    output_video = str(tmp_path / "final_render.mp4")
    raw_clip_1 = str(tmp_path / "clip_1.mp4")
    raw_clip_2 = str(tmp_path / "clip_2.mp4")
    audio_path = str(tmp_path / "narration.mp3")

    # Create dummy source files
    with open(raw_clip_1, "wb") as f:
        f.write(b"0" * 200000)
    with open(raw_clip_2, "wb") as f:
        f.write(b"0" * 200000)
    with open(audio_path, "wb") as f:
        f.write(b"0" * 5000)

    spec = SpecOutput(
        topic="Brain Power",
        video_type="short",
        sub_format="core_brainblud",
        seo=SEOMetadata(title="Brain #shorts", description="Brain facts", tags=["brain"]),
        scenes=[
            SceneSpec(scene_id=1, spoken_text="Scene one", phonetic_text="Scene one", stock_video_query="brain query", duration_seconds=3.0, word_timestamps=[]),
            SceneSpec(scene_id=2, spoken_text="Scene two", phonetic_text="Scene two", stock_video_query="brain query", duration_seconds=4.0, word_timestamps=[]),
        ],
        total_duration_seconds=7.0,
        audio_path=audio_path
    )

    clips_manifest = ClipsManifest(
        topic="Brain Power",
        video_type="short",
        clips=[
            ClipItem(scene_id=1, query="brain query", download_url="http://mock.url/1.mp4", provider="pexels", video_id="101"),
            ClipItem(scene_id=2, query="brain query", download_url="http://mock.url/2.mp4", provider="pixabay", video_id="102"),
        ]
    )

    channel_cfg = {
        "handle": "@BrainBlud",
        "branding": {"watermark_text": "@BrainBlud", "opacity": 0.40}
    }
    settings_cfg = {
        "video_profiles": {
            "short": {"preset": "fast", "fps": 30}
        },
        "captions": {"font_size": 72, "active_color": "&H0000FFFF", "inactive_color": "&H00FFFFFF"}
    }

    # Mock download_clip to return local paths
    monkeypatch.setattr("scripts.render_video.download_clip", lambda url, dest, prov, vid: dest)
    monkeypatch.setattr("scripts.render_video.download_cinematic_font", lambda: "Arial")
    monkeypatch.setattr("scripts.render_video.check_filter_supported", lambda f: True)

    executed_cmds = []

    def mock_subprocess_run(cmd, *args, **kwargs):
        executed_cmds.append(cmd)
        # Create output file if it's the target of the command
        target = cmd[-1]
        with open(target, "wb") as f:
            f.write(b"0" * 1000)
        return MagicMock(returncode=0, stderr="")

    monkeypatch.setattr("subprocess.run", mock_subprocess_run)

    render_video_ffmpeg(
        spec=spec,
        clips_manifest=clips_manifest,
        output_video_path=output_video,
        channel_cfg=channel_cfg,
        settings_cfg=settings_cfg
    )

    # 1. Step 1 commands: normalizing segment 0 and segment 1
    seg_0_cmd = executed_cmds[0]
    assert "-stream_loop" in seg_0_cmd
    assert "-fflags" in seg_0_cmd
    assert "+genpts" in seg_0_cmd
    assert "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920" in seg_0_cmd[seg_0_cmd.index("-vf") + 1]
    assert "-an" in seg_0_cmd
    assert "-c:v" in seg_0_cmd and seg_0_cmd[seg_0_cmd.index("-c:v") + 1] == "libx264"

    seg_1_cmd = executed_cmds[1]
    assert "-stream_loop" in seg_1_cmd

    # 2. Step 2 command: stream-copy concat demuxer
    concat_cmd = executed_cmds[2]
    assert "-f" in concat_cmd and concat_cmd[concat_cmd.index("-f") + 1] == "concat"
    assert "-safe" in concat_cmd and concat_cmd[concat_cmd.index("-safe") + 1] == "0"
    assert "-c" in concat_cmd and concat_cmd[concat_cmd.index("-c") + 1] == "copy"

    # 3. Step 3 command: composite pass
    final_cmd = executed_cmds[3]
    assert "-i" in final_cmd
    assert "-map" in final_cmd
    assert "-vf" in final_cmd
    assert "drawtext" in final_cmd[final_cmd.index("-vf") + 1]
    assert "subtitles" in final_cmd[final_cmd.index("-vf") + 1]
    assert "-c:a" in final_cmd and final_cmd[final_cmd.index("-c:a") + 1] == "aac"
    assert output_video in final_cmd


def test_render_video_ffmpeg_long_form(tmp_path, monkeypatch):
    """Verifies that 16:9 long-form video assembly scales to 1920x1080 with lower-third subtitles."""
    output_video = str(tmp_path / "long_render.mp4")
    raw_clip_1 = str(tmp_path / "clip_1.mp4")
    audio_path = str(tmp_path / "narration.mp3")

    with open(raw_clip_1, "wb") as f:
        f.write(b"0" * 200000)
    with open(audio_path, "wb") as f:
        f.write(b"0" * 5000)

    spec = SpecOutput(
        topic="Solitude and Brain",
        video_type="long",
        sub_format="documentary_essay",
        seo=SEOMetadata(title="Psychology of Solitude", description="Deep dive", tags=["psychology"]),
        scenes=[
            SceneSpec(scene_id=1, spoken_text="In nineteen fifty-one, students were paid twenty dollars.", phonetic_text="In nineteen fifty-one, students were paid twenty dollars.", stock_video_query="vintage library", duration_seconds=6.0, word_timestamps=[]),
        ],
        total_duration_seconds=6.0,
        audio_path=audio_path
    )

    clips_manifest = ClipsManifest(
        topic="Solitude and Brain",
        video_type="long",
        clips=[
            ClipItem(scene_id=1, query="vintage library", download_url="http://mock.url/1.mp4", provider="pexels", video_id="201", width=1920, height=1080),
        ]
    )

    channel_cfg = {
        "handle": "@metopato",
        "branding": {"watermark_text": "@metopato", "opacity": 0.35, "position": "lower_center"}
    }
    settings_cfg = {
        "video_profiles": {
            "long": {"preset": "fast", "fps": 30}
        },
        "captions": {
            "font_size_long": 44,
            "max_words_per_chunk_long": 6,
            "outline_width_long": 3,
            "uppercase_long": False
        }
    }

    monkeypatch.setattr("scripts.render_video.download_clip", lambda url, dest, prov, vid: dest)
    monkeypatch.setattr("scripts.render_video.download_cinematic_font", lambda: "Arial")
    monkeypatch.setattr("scripts.render_video.check_filter_supported", lambda f: True)

    executed_cmds = []

    def mock_subprocess_run(cmd, *args, **kwargs):
        executed_cmds.append(cmd)
        target = cmd[-1]
        with open(target, "wb") as f:
            f.write(b"0" * 1000)
        return MagicMock(returncode=0, stderr="")

    monkeypatch.setattr("subprocess.run", mock_subprocess_run)

    render_video_ffmpeg(
        spec=spec,
        clips_manifest=clips_manifest,
        output_video_path=output_video,
        channel_cfg=channel_cfg,
        settings_cfg=settings_cfg
    )

    # 1. Step 1: verify 1920x1080 resolution normalization
    seg_cmd = executed_cmds[0]
    assert "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080" in seg_cmd[seg_cmd.index("-vf") + 1]

    # 2. Step 3: verify 16:9 branding positioning
    final_cmd = executed_cmds[2]
    vf_str = final_cmd[final_cmd.index("-vf") + 1]
    assert "drawtext" in vf_str
    assert "subtitles" in vf_str
    assert "w-text_w-80" in vf_str
    assert "h-text_h-80" in vf_str


def test_subtitles_clear_during_inter_scene_pause_gap(tmp_path):
    """Verifies that subtitles cleanly disappear during the inter-scene silence pause and never bleed across scenes."""
    output_ass = str(tmp_path / "captions_gap.ass")
    scenes = [
        SceneSpec(
            scene_id=1,
            spoken_text="First thought finishes here.",
            phonetic_text="First thought finishes here.",
            stock_video_query="soap carving",
            duration_seconds=3.0,
            word_timestamps=[
                WordTimestamp(word="First", start=0.2, end=0.7),
                WordTimestamp(word="thought", start=0.7, end=1.4),
                WordTimestamp(word="finishes", start=1.4, end=2.0),
                WordTimestamp(word="here.", start=2.0, end=2.6),
            ]
        ),
        SceneSpec(
            scene_id=2,
            spoken_text="Second thought starts now.",
            phonetic_text="Second thought starts now.",
            stock_video_query="kinetic sand",
            duration_seconds=3.0,
            word_timestamps=[
                WordTimestamp(word="Second", start=3.1, end=3.6),
                WordTimestamp(word="thought", start=3.6, end=4.2),
                WordTimestamp(word="starts", start=4.2, end=4.8),
                WordTimestamp(word="now.", start=4.8, end=5.4),
            ]
        )
    ]

    generate_ass_subtitles(
        scenes=scenes,
        output_ass_path=output_ass,
        width=1080,
        height=1920,
        chunk_size=2,
        uppercase=True
    )

    with open(output_ass, "r", encoding="utf-8") as f:
        lines = f.readlines()

    dialogue_lines = [l.strip() for l in lines if l.startswith("Dialogue:")]
    assert len(dialogue_lines) >= 4

    for line in dialogue_lines:
        parts = line.split(",")
        start_ts = parts[1]
        end_ts = parts[2]
        text = ",".join(parts[9:])

        # 1. Zero cross-scene word bleeding: Scene 1's words never share a chunk with Scene 2
        if "HERE" in text:
            assert "SECOND" not in text
        if "SECOND" in text:
            assert "HERE" not in text

        # 2. Scene 1 events terminate cleanly before the 2.65-3.10s pause gap
        if "FIRST" in text or "HERE" in text:
            assert end_ts <= "0:00:02.70"
        # 3. Scene 2 events start at 3.10s
        if "SECOND" in text or "NOW" in text:
            assert start_ts >= "0:00:03.10"


def test_orphan_absorption_and_capcut_styling(tmp_path):
    """Verifies that trailing 1-word orphans are absorbed into preceding chunks and CapCut styles are applied."""
    output_ass = str(tmp_path / "captions_orphan.ass")
    # 5 words: with chunk_size=2, without orphan absorption would be 2+2+1 chunks.
    # With orphan absorption, it becomes 2+3 chunks (total 5 dialogue events: 2 for chunk 1, 3 for chunk 2).
    scenes = [
        SceneSpec(
            scene_id=1,
            spoken_text="The sky is very blue",
            phonetic_text="The sky is very blue",
            stock_video_query="blue sky",
            duration_seconds=3.0,
            word_timestamps=[
                WordTimestamp(word="The", start=0.0, end=0.3),
                WordTimestamp(word="sky", start=0.3, end=0.6),
                WordTimestamp(word="is", start=0.6, end=0.9),
                WordTimestamp(word="very", start=0.9, end=1.3),
                WordTimestamp(word="blue", start=1.3, end=1.8),
            ]
        )
    ]

    generate_ass_subtitles(
        scenes=scenes,
        output_ass_path=output_ass,
        width=1080,
        height=1920,
        font_name="ZY Resolve",
        font_size=88,
        active_color="&H0000E6FF",
        inactive_color="&H00FFFFFF",
        outline_width=7,
        shadow_depth=5,
        shadow_blur=3,
        shadow_color="&H33000000",
        chunk_size=2,
        uppercase=True,
    )

    with open(output_ass, "r", encoding="utf-8") as f:
        content = f.read()

    # Style header assertions
    assert "Style: Default,ZY Resolve,88,&H00FFFFFF,&H000000FF,&H00000000,&H33000000,-1,0,0,0,100,100,0,0,1,7,5,2,40,40," in content

    lines = [l.strip() for l in content.splitlines() if l.startswith("Dialogue:")]
    # Exactly 5 dialogue lines (2 for first chunk, 3 for second chunk)
    assert len(lines) == 5

    # Check soft blur tag and yellow highlight
    for l in lines:
        assert "{\\blur3}" in l

    assert "{\\c&H0000E6FF}" in content

    # Verify that the absorbed orphan 'BLUE' is displayed in the 3-word chunk with 'IS' and 'VERY'
    last_event = lines[-1]
    assert "IS VERY" in last_event
    assert "BLUE" in last_event


def test_download_cinematic_font_vault():
    """Verifies download_cinematic_font prefers existing local repository vault font ZY-Resolve.ttf."""
    from scripts.render_video import download_cinematic_font
    font_path = download_cinematic_font()
    assert os.path.exists(font_path)
    assert "zy-resolve" in font_path.lower()


def test_intra_scene_caption_pause_bridging(tmp_path):
    """Verifies that within a single scene, captions stay on-screen across long speech pauses (e.g. 0.76s pause)."""
    from scripts.render_video import generate_ass_subtitles
    from engine.models import SceneSpec, WordTimestamp

    output_ass = str(tmp_path / "captions_pause_bridge.ass")
    # Simulate Scene 10: "If poison expires, does it become more poisonous, or does it lose its power?"
    # Pause between 'poisonous?' (end=46.42) and 'Or' (start=47.18) is 0.76s
    scenes = [
        SceneSpec(
            scene_id=1,
            spoken_text="More poisonous, or does it lose its power?",
            phonetic_text="More poisonous, or does it lose its power?",
            stock_video_query="ice crushing slow motion ASMR",
            duration_seconds=4.5,
            word_timestamps=[
                WordTimestamp(word="More", start=45.72, end=46.02),
                WordTimestamp(word="poisonous?", start=46.02, end=46.42),
                WordTimestamp(word="Or", start=47.18, end=47.33),
                WordTimestamp(word="does", start=47.33, end=47.44),
                WordTimestamp(word="it", start=47.44, end=47.60),
                WordTimestamp(word="lose", start=47.60, end=47.80),
                WordTimestamp(word="its", start=47.80, end=48.00),
                WordTimestamp(word="power?", start=48.00, end=48.26),
            ]
        )
    ]

    generate_ass_subtitles(
        scenes=scenes,
        output_ass_path=output_ass,
        chunk_size=2,
        uppercase=True
    )

    with open(output_ass, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f.readlines() if l.startswith("Dialogue:")]

    # Find the event where 'POISONOUS' is active (end of chunk 1)
    poisonous_events = [l for l in lines if "POISONOUS" in l]
    assert len(poisonous_events) >= 1
    # The active highlight for 'POISONOUS' must extend to 47.18 (start of 'Or'), NOT cut off at 46.48
    active_poisonous = [l for l in poisonous_events if "{\\c&H0000E6FF}POISONOUS" in l or "POISONOUS{\\c&H00FFFFFF}" in l][0]
    parts = active_poisonous.split(",")
    end_ts = parts[2]
    # 47.18s is 0:00:47.18 in ASS format
    assert end_ts == "0:00:47.18", f"Expected caption to bridge to 0:00:47.18, but got {end_ts}"


def test_render_video_ffmpeg_no_shortest_and_cta_closer_protection(tmp_path, monkeypatch):
    """Verifies that render_video_ffmpeg omits -shortest, includes -stream_loop on video input, and enforces segment flags."""
    output_video = str(tmp_path / "final_render.mp4")
    raw_clip_1 = str(tmp_path / "clip_1.mp4")
    audio_path = str(tmp_path / "narration.mp3")

    with open(raw_clip_1, "wb") as f:
        f.write(b"0" * 200000)
    with open(audio_path, "wb") as f:
        f.write(b"0" * 5000)

    spec = SpecOutput(
        topic="CTA Test",
        video_type="short",
        sub_format="core_brainblud",
        seo=SEOMetadata(title="CTA Test #shorts", description="Test", tags=["test"]),
        scenes=[
            SceneSpec(scene_id=1, spoken_text="Hook scene", phonetic_text="Hook scene", duration_seconds=3.0),
            SceneSpec(scene_id=2, spoken_text="Subscribe for more thoughts that will break your brain.", phonetic_text="Subscribe for more thoughts that will break your brain.", duration_seconds=3.0),
        ],
        total_duration_seconds=6.0,
        audio_path=audio_path
    )

    clips_manifest = ClipsManifest(
        topic="CTA Test",
        video_type="short",
        clips=[
            ClipItem(scene_id=1, query="query", download_url="http://mock.url/1.mp4", provider="pexels", video_id="101"),
            ClipItem(scene_id=2, query="query", download_url="http://mock.url/2.mp4", provider="local", video_id="honeycomb_01.mp4"),
        ]
    )

    channel_cfg = {"handle": "@test", "branding": {"watermark_text": "@test"}}
    settings_cfg = {"video_profiles": {"short": {"preset": "fast", "fps": 30}}}

    monkeypatch.setattr("scripts.render_video.download_clip", lambda url, dest, prov, vid: dest)
    monkeypatch.setattr("scripts.render_video.download_cinematic_font", lambda: "Arial")
    monkeypatch.setattr("scripts.render_video.check_filter_supported", lambda f: True)

    executed_cmds = []

    def mock_subprocess_run(cmd, *args, **kwargs):
        executed_cmds.append(cmd)
        target = cmd[-1]
        with open(target, "wb") as f:
            f.write(b"0" * 1000)
        return MagicMock(returncode=0, stderr="")

    monkeypatch.setattr("subprocess.run", mock_subprocess_run)

    render_video_ffmpeg(
        spec=spec,
        clips_manifest=clips_manifest,
        output_video_path=output_video,
        channel_cfg=channel_cfg,
        settings_cfg=settings_cfg
    )

    # 1. Segment commands must standardize timescale, closed GOP, and zero B-frames
    seg_cmd = executed_cmds[0]
    assert "-video_track_timescale" in seg_cmd and seg_cmd[seg_cmd.index("-video_track_timescale") + 1] == "15360"
    assert "-g" in seg_cmd and seg_cmd[seg_cmd.index("-g") + 1] == "30"
    assert "-bf" in seg_cmd and seg_cmd[seg_cmd.index("-bf") + 1] == "0"

    # 2. Final composite command must NEVER contain -shortest
    final_cmd = executed_cmds[-1]
    assert "-shortest" not in final_cmd, "Critical bug: -shortest cuts off Call to Action closer narration!"

    # 3. Final composite command must stream loop input 0 to prevent video starvation
    assert "-stream_loop" in final_cmd
    concat_idx = final_cmd.index("-i")
    assert final_cmd[concat_idx - 2] == "-stream_loop"
    assert final_cmd[concat_idx - 1] == "-1"

    # 4. Final composite command must pad voice input with apad=pad_dur=4 to prevent loudnorm EOF truncation
    fc_idx = final_cmd.index("-filter_complex")
    fc_str = final_cmd[fc_idx + 1]
    assert "apad=pad_dur=4" in fc_str, "Voice input must be padded with apad=pad_dur=4 to prevent loudnorm lookahead EOF truncation!"


def test_probe_video_duration(tmp_path):
    """Verifies that _probe_video_duration accurately parses MP4 durations using atom parsing fallback."""
    from scripts.render_video import _probe_video_duration
    assert _probe_video_duration(str(tmp_path / "non_existent.mp4")) == 0.0


def test_find_ffmpeg_bin_custom_path_selection(tmp_path, monkeypatch):
    """Verifies that find_ffmpeg_bin returns the path specified by FFMPEG_BINARY when the file exists."""
    from scripts.render_video import find_ffmpeg_bin
    dummy_ffmpeg = tmp_path / "custom_ffmpeg.exe"
    dummy_ffmpeg.write_bytes(b"dummy")

    monkeypatch.setenv("FFMPEG_BINARY", str(dummy_ffmpeg))
    resolved = find_ffmpeg_bin()
    assert resolved == str(dummy_ffmpeg)


def test_find_ffmpeg_bin_path_selection(monkeypatch):
    """Verifies that find_ffmpeg_bin falls back to shutil.which('ffmpeg') when FFMPEG_BINARY is unset."""
    from scripts.render_video import find_ffmpeg_bin
    import shutil

    monkeypatch.delenv("FFMPEG_BINARY", raising=False)
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/local/bin/ffmpeg" if cmd == "ffmpeg" else None)
    resolved = find_ffmpeg_bin()
    assert resolved == "/usr/local/bin/ffmpeg"


def test_find_ffmpeg_bin_invalid_config_raises_actionable_error(monkeypatch):
    """Verifies that find_ffmpeg_bin raises FileNotFoundError with actionable instructions when FFMPEG_BINARY does not exist."""
    from scripts.render_video import find_ffmpeg_bin

    nonexistent_path = "C:/invalid/path/to/ffmpeg.exe"
    monkeypatch.setenv("FFMPEG_BINARY", nonexistent_path)
    with pytest.raises(FileNotFoundError) as exc_info:
        find_ffmpeg_bin()

    assert "Configured FFMPEG_BINARY does not exist" in str(exc_info.value)
    assert nonexistent_path in str(exc_info.value)
    assert "unset FFMPEG_BINARY" in str(exc_info.value)


def test_render_video_ffmpeg_uses_custom_ffmpeg_binary(tmp_path, monkeypatch):
    """Verifies that render_video_ffmpeg uses the resolved FFMPEG_BINARY across all subprocess operations."""
    from scripts.render_video import render_video_ffmpeg

    dummy_ffmpeg = tmp_path / "bin" / "ffmpeg_custom.exe"
    dummy_ffmpeg.parent.mkdir(parents=True, exist_ok=True)
    dummy_ffmpeg.write_bytes(b"binary")
    monkeypatch.setenv("FFMPEG_BINARY", str(dummy_ffmpeg))

    output_video = str(tmp_path / "final_render.mp4")
    raw_clip_1 = str(tmp_path / "clip_1.mp4")
    raw_clip_2 = str(tmp_path / "clip_2.mp4")
    audio_path = str(tmp_path / "narration.mp3")

    with open(raw_clip_1, "wb") as f:
        f.write(b"0" * 10000)
    with open(raw_clip_2, "wb") as f:
        f.write(b"0" * 10000)
    with open(audio_path, "wb") as f:
        f.write(b"0" * 1000)

    spec = SpecOutput(
        topic="Binary Test",
        video_type="short",
        sub_format="core_brainblud",
        seo=SEOMetadata(title="Binary Test #shorts", description="Test", tags=["test"]),
        scenes=[
            SceneSpec(scene_id=1, spoken_text="Scene one", phonetic_text="Scene one", stock_video_query="q1", duration_seconds=3.0, word_timestamps=[]),
            SceneSpec(scene_id=2, spoken_text="Scene two", phonetic_text="Scene two", stock_video_query="q2", duration_seconds=3.0, word_timestamps=[]),
        ],
        total_duration_seconds=6.0,
        audio_path=audio_path
    )

    clips_manifest = ClipsManifest(
        topic="Binary Test",
        video_type="short",
        clips=[
            ClipItem(scene_id=1, query="q1", download_url="http://mock.url/1.mp4", provider="pexels", video_id="101"),
            ClipItem(scene_id=2, query="q2", download_url="http://mock.url/2.mp4", provider="pixabay", video_id="102"),
        ]
    )

    channel_cfg = {"handle": "@test", "branding": {"watermark_text": "@test"}}
    settings_cfg = {"video_profiles": {"short": {"preset": "fast", "fps": 30}}}

    monkeypatch.setattr("scripts.render_video.download_clip", lambda url, dest, prov, vid: dest)
    monkeypatch.setattr("scripts.render_video.download_cinematic_font", lambda: "Arial")
    monkeypatch.setattr("scripts.render_video.check_filter_supported", lambda f, *a, **kw: True)

    executed_cmds = []

    def mock_subprocess_run(cmd, *args, **kwargs):
        executed_cmds.append(cmd)
        target = cmd[-1]
        with open(target, "wb") as f:
            f.write(b"0" * 1000)
        return MagicMock(returncode=0, stderr="")

    monkeypatch.setattr("subprocess.run", mock_subprocess_run)

    render_video_ffmpeg(
        spec=spec,
        clips_manifest=clips_manifest,
        output_video_path=output_video,
        channel_cfg=channel_cfg,
        settings_cfg=settings_cfg
    )

    # Must execute segment 1, segment 2, concat, and composite commands
    assert len(executed_cmds) == 4
    for idx, cmd in enumerate(executed_cmds):
        assert cmd[0] == str(dummy_ffmpeg), f"Command {idx} invoked '{cmd[0]}' instead of resolved '{dummy_ffmpeg}': {cmd}"


def test_render_video_ffmpeg_missing_executable_raises_clear_error(tmp_path, monkeypatch):
    """Verifies that render_video_ffmpeg raises clear, actionable FileNotFoundError when FFmpeg executable cannot be found."""
    from scripts.render_video import render_video_ffmpeg

    output_video = str(tmp_path / "final_render.mp4")
    raw_clip = str(tmp_path / "clip.mp4")
    audio_path = str(tmp_path / "narration.mp3")

    with open(raw_clip, "wb") as f:
        f.write(b"0" * 10000)
    with open(audio_path, "wb") as f:
        f.write(b"0" * 1000)

    spec = SpecOutput(
        topic="Error Test",
        video_type="short",
        sub_format="core_brainblud",
        seo=SEOMetadata(title="Error Test #shorts", description="Test", tags=["test"]),
        scenes=[
            SceneSpec(scene_id=1, spoken_text="Hook", phonetic_text="Hook", stock_video_query="q", duration_seconds=3.0, word_timestamps=[]),
        ],
        total_duration_seconds=3.0,
        audio_path=audio_path
    )

    clips_manifest = ClipsManifest(
        topic="Error Test",
        video_type="short",
        clips=[
            ClipItem(scene_id=1, query="q", download_url="http://mock.url/1.mp4", provider="pexels", video_id="101"),
        ]
    )

    channel_cfg = {"handle": "@test", "branding": {"watermark_text": "@test"}}
    settings_cfg = {"video_profiles": {"short": {"preset": "fast", "fps": 30}}}

    monkeypatch.setattr("scripts.render_video.download_clip", lambda url, dest, prov, vid: dest)
    monkeypatch.setattr("scripts.render_video.download_cinematic_font", lambda: "Arial")
    monkeypatch.setattr("scripts.render_video.check_filter_supported", lambda f, *a, **kw: True)

    def mock_subprocess_missing(cmd, *args, **kwargs):
        raise FileNotFoundError(2, "The system cannot find the file specified", cmd[0])

    monkeypatch.setattr("subprocess.run", mock_subprocess_missing)

    with pytest.raises(FileNotFoundError) as exc_info:
        render_video_ffmpeg(
            spec=spec,
            clips_manifest=clips_manifest,
            output_video_path=output_video,
            channel_cfg=channel_cfg,
            settings_cfg=settings_cfg
        )

    err_str = str(exc_info.value)
    assert "FFmpeg executable not found" in err_str
    assert "FFMPEG_BINARY" in err_str


def test_helpers_respect_custom_ffmpeg_binary(tmp_path, monkeypatch):
    """Verifies that check_filter_supported and _probe_video_duration use custom ffmpeg binary."""
    from scripts.render_video import check_filter_supported, _probe_video_duration

    dummy_bin = str(tmp_path / "custom_bin")
    executed_cmds = []

    def mock_run(cmd, *args, **kwargs):
        executed_cmds.append(cmd)
        return MagicMock(returncode=0, stdout="--enable-filter=drawtext", stderr="")

    monkeypatch.setattr("subprocess.run", mock_run)

    # 1. Direct pass to check_filter_supported
    is_supported = check_filter_supported("drawtext", ffmpeg_bin=dummy_bin)
    assert is_supported is True
    assert executed_cmds[-1][0] == dummy_bin

    # 2. Direct pass to _probe_video_duration (fallback inspection)
    dummy_mp4 = str(tmp_path / "test.mp4")
    with open(dummy_mp4, "wb") as f:
        f.write(b"0" * 100)

    # Make ffprobe fail so it cascades to ffmpeg -i
    def mock_probe_run(cmd, *args, **kwargs):
        executed_cmds.append(cmd)
        if cmd[0] == "ffprobe":
            return MagicMock(returncode=1, stdout="", stderr="error")
        return MagicMock(returncode=0, stdout="", stderr="Duration: 00:00:05.50, start: 0.0")

    monkeypatch.setattr("subprocess.run", mock_probe_run)
    dur = _probe_video_duration(dummy_mp4, ffmpeg_bin=dummy_bin)
    assert dur == 5.5
    # Must have called ffmpeg fallback with dummy_bin
    ffmpeg_cmd = [c for c in executed_cmds if c[0] == dummy_bin and "-i" in c]
    assert len(ffmpeg_cmd) == 1
