from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


# transcribe_with_frames has an optional external Whisper helper at import time.
if "whisper" not in sys.modules:
    whisper_stub = types.ModuleType("whisper")
    whisper_stub._post_whisper = lambda *args, **kwargs: None
    whisper_stub.GROQ_ENDPOINT = ""
    whisper_stub.GROQ_MODEL = ""
    whisper_stub.load_api_key = lambda: ("groq", "test")
    sys.modules["whisper"] = whisper_stub

from scripts import transcribe_with_frames as pipeline  # noqa: E402


def completed(returncode: int, *, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["ffmpeg"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class LocalMediaProbeTests(unittest.TestCase):
    @patch("scripts.transcribe_with_frames.subprocess.run")
    def test_probe_requires_an_audio_stream(self, run_mock):
        run_mock.return_value = completed(
            0,
            stdout=json.dumps({
                "format": {"duration": "12.5"},
                "streams": [{"codec_type": "video"}],
            }),
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "silent.mp4"
            source.write_bytes(b"media")
            with self.assertRaisesRegex(ValueError, "playable audio stream"):
                pipeline._probe_local_media(source)

        command = run_mock.call_args.args[0]
        self.assertEqual(command[0], "ffprobe")
        self.assertIn("-show_streams", command)
        self.assertIn("-protocol_whitelist", command)
        self.assertEqual(
            run_mock.call_args.kwargs["timeout"],
            pipeline.LOCAL_MEDIA_PROBE_TIMEOUT_SECONDS,
        )

    @patch("scripts.transcribe_with_frames.subprocess.run")
    def test_probe_uses_audio_duration_and_detects_video(self, run_mock):
        run_mock.return_value = completed(
            0,
            stdout=json.dumps({
                "format": {"duration": "N/A"},
                "streams": [
                    {"codec_type": "audio", "duration": "7.25"},
                    {"codec_type": "video"},
                ],
            }),
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "clip.mp4"
            source.write_bytes(b"media")
            result = pipeline._probe_local_media(source)

        self.assertEqual(result["duration"], 7.25)
        self.assertTrue(result["has_audio"])
        self.assertTrue(result["has_video"])

    @patch("scripts.transcribe_with_frames.subprocess.run")
    def test_probe_rejects_unreadable_media(self, run_mock):
        run_mock.return_value = completed(1, stderr="Invalid data found")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "broken.mp4"
            source.write_bytes(b"not-media")
            with self.assertRaisesRegex(ValueError, "not readable by ffprobe"):
                pipeline._probe_local_media(source)

    @patch("scripts.transcribe_with_frames.subprocess.run")
    def test_probe_rejects_media_longer_than_two_hours(self, run_mock):
        run_mock.return_value = completed(
            0,
            stdout=json.dumps({
                "format": {"duration": "7200.01"},
                "streams": [{"codec_type": "audio"}],
            }),
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "too-long.mp4"
            source.write_bytes(b"media")
            with self.assertRaisesRegex(ValueError, "2-hour limit"):
                pipeline._probe_local_media(source)

    @patch("scripts.transcribe_with_frames.subprocess.run")
    def test_probe_timeout_is_reported_cleanly(self, run_mock):
        run_mock.side_effect = subprocess.TimeoutExpired(
            cmd=["ffprobe"], timeout=pipeline.LOCAL_MEDIA_PROBE_TIMEOUT_SECONDS
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "slow.mp4"
            source.write_bytes(b"media")
            with self.assertRaisesRegex(ValueError, "Timed out"):
                pipeline._probe_local_media(source)


class LocalMediaFrameTests(unittest.TestCase):
    @patch("scripts.transcribe_with_frames.subprocess.run")
    def test_short_static_video_gets_one_representative_frame(self, run_mock):
        def fake_run(command, **_kwargs):
            if "grid_00001.jpg" in str(command[-1]) and "-ss" in command:
                Path(command[-1]).write_bytes(b"jpeg")
            return completed(0)

        run_mock.side_effect = fake_run
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "short.mp4"
            source.write_bytes(b"media")
            frames = pipeline.extract_scene_frames(
                source,
                3.0,
                root / "frames",
                local_only=True,
            )

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0][0], 1.5)
        representative_command = run_mock.call_args_list[-1].args[0]
        self.assertIn("-frames:v", representative_command)
        self.assertIn("yuvj420p", representative_command)


class LocalMediaTranscodeTests(unittest.TestCase):
    @patch("scripts.transcribe_with_frames._run")
    def test_transcodes_to_canonical_session_mp3(self, run_mock):
        def encode(command, **_kwargs):
            Path(command[-1]).write_bytes(b"mp3")
            return completed(0)

        run_mock.side_effect = encode
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "upload.mp4"
            source.write_bytes(b"media")
            output = pipeline._ensure_local_audio(source, root)

            self.assertEqual(output, root / "session_full.mp3")
            self.assertEqual(output.read_bytes(), b"mp3")
            self.assertFalse((root / "session_full.tmp.mp3").exists())

        command = run_mock.call_args.args[0]
        self.assertEqual(command[0], "ffmpeg")
        self.assertIn("-nostdin", command)
        self.assertIn("-protocol_whitelist", command)
        self.assertIn("-vn", command)
        self.assertIn(str(source), command)
        self.assertEqual(
            run_mock.call_args.kwargs["timeout"],
            pipeline.LOCAL_MEDIA_FFMPEG_TIMEOUT_SECONDS,
        )

    @patch("scripts.transcribe_with_frames._run")
    def test_failed_transcode_does_not_leave_partial_output(self, run_mock):
        run_mock.return_value = completed(1, stderr="decode failed")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "upload.mp4"
            source.write_bytes(b"media")
            with self.assertRaisesRegex(RuntimeError, "could not decode"):
                pipeline._ensure_local_audio(source, root)
            self.assertFalse((root / "session_full.tmp.mp3").exists())
            self.assertFalse((root / "session_full.mp3").exists())


class LocalMediaPipelineTests(unittest.TestCase):
    @patch("scripts.transcribe_with_frames._ensure_local_audio")
    @patch("scripts.transcribe_with_frames._probe_local_media")
    @patch("scripts.transcribe_with_frames.run_ytdlp")
    def test_frames_require_a_video_stream(self, ytdlp_mock, probe_mock,
                                           audio_mock):
        probe_mock.return_value = {
            "duration": 30.0, "has_audio": True, "has_video": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "voice.mp3"
            source.write_bytes(b"media")
            with self.assertRaisesRegex(ValueError, "requires.*video stream"):
                pipeline.run_local_media_pipeline(
                    source, Path(directory) / "work",
                    title="Voice", video_id="local-1", extract_frames=True,
                )

        audio_mock.assert_not_called()
        ytdlp_mock.assert_not_called()

    @patch("scripts.transcribe_with_frames.write_outputs")
    @patch("scripts.transcribe_with_frames.transcribe_chunks")
    @patch("scripts.transcribe_with_frames.split_audio")
    @patch("scripts.transcribe_with_frames._ensure_local_audio")
    @patch("scripts.transcribe_with_frames.write_final_frames", return_value=[])
    @patch("scripts.transcribe_with_frames.dedupe_frames", return_value=[])
    @patch("scripts.transcribe_with_frames.extract_scene_frames", return_value=[])
    @patch("scripts.transcribe_with_frames._probe_local_media")
    @patch("scripts.transcribe_with_frames.run_ytdlp")
    def test_frame_only_mode_skips_all_transcription_work(
        self, ytdlp_mock, probe_mock, _extract_mock, _dedupe_mock,
        _final_mock, audio_mock, split_mock, transcribe_mock, outputs_mock,
    ):
        probe_mock.return_value = {
            "duration": 45.0, "has_audio": True, "has_video": True,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "video.mp4"
            source.write_bytes(b"media")
            result = pipeline.run_local_media_pipeline(
                source, root / "work", title="Frames", video_id="local-frames",
                extract_frames=True, transcribe=False,
            )

        self.assertIsNone(result["transcript_txt"])
        self.assertIsNone(result["transcript_json"])
        self.assertIsNone(result["transcript_with_frames"])
        self.assertEqual(result["segments_count"], 0)
        audio_mock.assert_not_called()
        split_mock.assert_not_called()
        transcribe_mock.assert_not_called()
        outputs_mock.assert_not_called()
        ytdlp_mock.assert_not_called()

    @patch("scripts.transcribe_with_frames.write_outputs")
    @patch("scripts.transcribe_with_frames.transcribe_chunks")
    @patch("scripts.transcribe_with_frames.split_audio")
    @patch("scripts.transcribe_with_frames._ensure_local_audio")
    @patch("scripts.transcribe_with_frames._probe_local_media")
    @patch("scripts.transcribe_with_frames.run_ytdlp")
    def test_audio_only_pipeline_reuses_transcript_helpers(
        self, ytdlp_mock, probe_mock, audio_mock, split_mock,
        transcribe_mock, outputs_mock,
    ):
        probe_mock.return_value = {
            "duration": 65.5, "has_audio": True, "has_video": False,
        }
        transcribe_mock.return_value = [
            {"start": 0.0, "end": 1.0, "chunk": 1, "text": "Hello"}
        ]
        outputs_mock.return_value = {
            "transcript_txt": Path("transcript.txt"),
            "transcript_json": Path("transcript.json"),
            "transcript_with_frames": None,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "voice.m4a"
            source.write_bytes(b"media")
            work = root / "work"
            audio_mock.return_value = work / "session_full.mp3"
            split_mock.return_value = [(work / "chunk_01.mp3", 0.0, 65.5)]

            result = pipeline.run_local_media_pipeline(
                source, work, title="Lesson", video_id="telegram-42",
                extract_frames=False,
            )

        self.assertEqual(result["video_id"], "telegram-42")
        self.assertEqual(result["title"], "Lesson")
        self.assertEqual(result["duration_seconds"], 65.5)
        self.assertEqual(result["segments_count"], 1)
        self.assertEqual(result["frames_count"], 0)
        self.assertIsNone(result["frames_dir"])
        self.assertIsNone(result["frames_index"])
        split_mock.assert_called_once_with(
            audio_mock.return_value, work, on_progress=None
        )
        transcribe_mock.assert_called_once_with(
            split_mock.return_value, on_progress=None
        )
        outputs_mock.assert_called_once_with(transcribe_mock.return_value, work, None)
        ytdlp_mock.assert_not_called()

    @patch("scripts.transcribe_with_frames.write_outputs")
    @patch("scripts.transcribe_with_frames.transcribe_chunks", return_value=[])
    @patch("scripts.transcribe_with_frames.split_audio", return_value=[])
    @patch("scripts.transcribe_with_frames.write_final_frames")
    @patch("scripts.transcribe_with_frames.dedupe_frames")
    @patch("scripts.transcribe_with_frames.extract_scene_frames")
    @patch("scripts.transcribe_with_frames._ensure_local_audio")
    @patch("scripts.transcribe_with_frames._probe_local_media")
    @patch("scripts.transcribe_with_frames.run_ytdlp")
    def test_video_pipeline_reuses_frame_helpers(
        self, ytdlp_mock, probe_mock, audio_mock, extract_mock, dedupe_mock,
        final_mock, _split_mock, _transcribe_mock, outputs_mock,
    ):
        probe_mock.return_value = {
            "duration": 90.0, "has_audio": True, "has_video": True,
        }
        candidates = [(1.0, Path("candidate.jpg"))]
        extract_mock.return_value = candidates
        dedupe_mock.return_value = candidates
        final_mock.return_value = [
            {"timestamp": 1.0, "file": "frame_00-00-01.jpg"}
        ]
        outputs_mock.return_value = {
            "transcript_txt": Path("transcript.txt"),
            "transcript_json": Path("transcript.json"),
            "transcript_with_frames": Path("transcript_with_frames.txt"),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "video.mp4"
            source.write_bytes(b"media")
            work = root / "work"
            audio_mock.return_value = work / "session_full.mp3"

            result = pipeline.run_local_media_pipeline(
                source, work, title="Video", video_id="telegram-99",
                extract_frames=True,
            )

            self.assertEqual(result["frames_dir"], work / "frames")
            self.assertEqual(result["frames_index"], work / "frames.json")
        self.assertEqual(result["frames_count"], 1)
        extract_mock.assert_called_once_with(
            source, 90.0, work / "frames",
            on_progress=None, local_only=True,
        )
        dedupe_mock.assert_called_once_with(candidates, on_progress=None)
        final_mock.assert_called_once_with(
            candidates, work / "frames", work / "frames.json"
        )
        ytdlp_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
