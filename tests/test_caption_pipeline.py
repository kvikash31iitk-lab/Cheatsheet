from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


# Keep this unit suite independent from the optional external Whisper helper.
if "whisper" not in sys.modules:
    whisper_stub = types.ModuleType("whisper")
    whisper_stub.GROQ_MODEL = "whisper-test"
    whisper_stub.load_api_key = lambda: ("groq", "test")
    sys.modules["whisper"] = whisper_stub

from scripts import transcribe_with_frames as pipeline  # noqa: E402


class CaptionPipelineTests(unittest.TestCase):
    def test_caption_items_are_cleaned_and_timestamped(self):
        rows = [
            {"text": "<i>Hello&nbsp;world</i>", "start": 2.0, "duration": 3.5},
            {"text": "Next   point", "start": 6.0, "duration": 2.0},
        ]

        segments = pipeline._caption_segments_from_items(rows)

        self.assertEqual(segments[0]["text"], "Hello world")
        self.assertEqual(segments[0]["end"], 5.5)
        self.assertEqual(segments[1]["chunk"], 1)

    @patch("scripts.transcribe_with_frames.ensure_audio")
    @patch("scripts.transcribe_with_frames.fetch_metadata_resilient")
    @patch("scripts.transcribe_with_frames.try_caption_transcript")
    def test_caption_success_skips_media_download(
        self, caption_mock, metadata_mock, audio_mock
    ):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            segments = [
                {
                    "start": 0.0,
                    "end": 12.0,
                    "chunk": 1,
                    "text": "A useful caption transcript with enough content.",
                }
            ]
            outputs = pipeline.write_outputs(segments, work, None)
            caption_mock.return_value = {
                **outputs,
                "provider": "youtube_transcript_api",
                "segments": segments,
            }
            metadata_mock.return_value = {
                "id": "abcdefghijk",
                "title": "Caption video",
                "duration": 0.0,
            }

            result = pipeline.run_pipeline(
                "https://youtu.be/abcdefghijk",
                work,
                extract_frames=False,
            )

            audio_mock.assert_not_called()
            self.assertEqual(result["transcript_provider"], "youtube_transcript_api")
            self.assertEqual(result["duration_seconds"], 12.0)
            source = json.loads((work / "source.json").read_text(encoding="utf-8"))
            self.assertEqual(source["transcript_provider"], "youtube_transcript_api")

    @patch("scripts.transcribe_with_frames.write_outputs")
    @patch("scripts.transcribe_with_frames.transcribe_chunks")
    @patch("scripts.transcribe_with_frames.split_audio")
    @patch("scripts.transcribe_with_frames.ensure_audio")
    @patch("scripts.transcribe_with_frames.fetch_metadata_resilient")
    @patch("scripts.transcribe_with_frames.try_caption_transcript")
    def test_no_captions_uses_audio_transcription(
        self,
        caption_mock,
        metadata_mock,
        audio_mock,
        split_mock,
        transcribe_mock,
        outputs_mock,
    ):
        caption_mock.return_value = None
        metadata_mock.return_value = {
            "id": "abcdefghijk",
            "title": "Audio video",
            "duration": 30.0,
        }
        segments = [{"start": 0.0, "end": 3.0, "chunk": 1, "text": "Audio text"}]
        transcribe_mock.return_value = segments
        split_mock.return_value = [(Path("chunk.mp3"), 0.0, 30.0)]
        audio_mock.return_value = Path("audio.mp3")

        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            transcript = work / "transcript.txt"
            transcript.write_text("Audio text", encoding="utf-8")
            outputs_mock.return_value = {
                "transcript_txt": transcript,
                "transcript_json": work / "transcript.json",
                "transcript_with_frames": None,
            }
            result = pipeline.run_pipeline(
                "https://youtu.be/abcdefghijk",
                work,
                extract_frames=False,
            )

        audio_mock.assert_called_once()
        transcribe_mock.assert_called_once()
        self.assertEqual(result["transcript_provider"], "whisper")


if __name__ == "__main__":
    unittest.main()
