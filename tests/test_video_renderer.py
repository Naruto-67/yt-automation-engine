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
    # Verify word-by-word highlighting tag
    assert "{\\c&H0000FFFF}" in content
    assert "The" in content
    assert "brain" in content


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

    class MockPopen:
        def __init__(self, cmd, *args, **kwargs):
            executed_cmds.append(cmd)
            self.returncode = 0
            self.stderr = MagicMock()
            self.stderr.readline.side_effect = [
                "frame=  100 fps= 60 time=00:00:03.00\n",
                ""
            ]

        def wait(self, timeout=None):
            # Create final video output
            with open(output_video, "wb") as f:
                f.write(b"0" * 50000)
            return 0

    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    monkeypatch.setattr("subprocess.Popen", MockPopen)

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

