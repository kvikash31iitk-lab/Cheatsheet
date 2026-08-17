from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from scripts.run_local_job import run_url_job


def _write_test_pdf(path: Path) -> None:
    from reportlab.pdfgen import canvas

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(target))
    for index in range(8):
        pdf.drawString(
            72,
            760 - index * 24,
            f"Validated PDF line {index}: substantial generated study material.",
        )
    pdf.save()


class LocalJobFlowTests(unittest.TestCase):
    @patch("scripts.run_local_job.build_cheatsheet")
    @patch("scripts.run_local_job.author_cheatsheet")
    @patch("scripts.run_local_job.run_pipeline")
    @patch("scripts.run_local_job.validate_public_youtube_url")
    def test_cheatsheet_flow_runs_all_stages(
        self, validate_mock, pipeline_mock, author_mock, render_mock
    ):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "job"
            transcript = work / "transcript.txt"
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text(
                "00:00 introduction with enough transcript material for the pipeline",
                encoding="utf-8",
            )

            pipeline_mock.return_value = {
                "video_id": "dQw4w9WgXcQ",
                "title": "Sample",
                "duration_seconds": 125.5,
                "transcript_txt": transcript,
                "transcript_json": None,
                "transcript_with_frames": None,
                "frames_dir": work / "frames",
                "frames_index": None,
            }
            author_mock.return_value = "# Output\n\n" + ("Substantial study material. " * 20)

            validate_mock.return_value = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            render_mock.side_effect = lambda *args, **kwargs: _write_test_pdf(args[1])
            ingest_events: list[dict[str, object]] = []
            cost_sink: dict[str, int] = {}
            out = run_url_job(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                kind="cheatsheet",
                work_root=work,
                use_cached_pipeline=False,
                progress=False,
                on_ingest=ingest_events.append,
                cost_sink=cost_sink,
            )

            pipeline_mock.assert_called_once()
            author_mock.assert_called_once_with(
                transcript,
                title_hint="Sample",
                duration_seconds=125.5,
                on_progress=unittest.mock.ANY,
                features=[],
                cost_sink=cost_sink,
            )
            self.assertEqual(len(ingest_events), 1)
            self.assertEqual(ingest_events[0]["video_id"], "dQw4w9WgXcQ")
            self.assertEqual(ingest_events[0]["title"], "Sample")
            self.assertEqual(ingest_events[0]["duration_seconds"], 125.5)
            render_mock.assert_called_once()
            self.assertTrue(Path(out["pdf_path"]).parent.exists())
            self.assertTrue(Path(out["markdown_path"]).exists())
            manifest = json.loads(
                Path(out["manifest_path"]).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(
                manifest["stages"]["quality_gate"]["status"], "complete"
            )

    @patch("scripts.run_local_job.build_book")
    @patch("scripts.run_local_job.author_book")
    @patch("scripts.run_local_job.run_pipeline")
    @patch("scripts.run_local_job.validate_public_youtube_url")
    def test_book_flow_uses_frames_dir_for_render(
        self, validate_mock, pipeline_mock, author_mock, render_mock
    ):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory) / "job"
            transcript = work / "transcript.txt"
            transcript.parent.mkdir(parents=True, exist_ok=True)
            transcript.write_text(
                "00:00 introduction with enough transcript material for the pipeline",
                encoding="utf-8",
            )
            frames_dir = work / "frames"
            frames_dir.mkdir()
            frames_index = frames_dir / "frames.json"
            frames_index.write_text("[]", encoding="utf-8")

            pipeline_mock.return_value = {
                "video_id": "dQw4w9WgXcQ",
                "title": "Sample book",
                "duration_seconds": 200.0,
                "transcript_txt": transcript,
                "transcript_json": None,
                "transcript_with_frames": frames_dir / "combined.txt",
                "frames_dir": frames_dir,
                "frames_index": frames_index,
            }
            author_mock.return_value = "# Sample Book\n\n" + ("Detailed book material. " * 20)
            validate_mock.return_value = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

            render_mock.side_effect = lambda *args, **kwargs: _write_test_pdf(args[1])

            out = run_url_job(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                kind="book",
                work_root=work,
                use_cached_pipeline=False,
                progress=False,
            )

            author_mock.assert_called_once()
            render_mock.assert_called_once()
            self.assertEqual(render_mock.call_args.args[0], Path(out["markdown_path"]))
            self.assertIsNotNone(render_mock.call_args.args[3])

    @patch("scripts.run_local_job.build_cheatsheet")
    @patch("scripts.run_local_job.author_cheatsheet")
    @patch("scripts.run_local_job.run_pipeline")
    @patch("scripts.run_local_job.validate_public_youtube_url")
    def test_second_run_reuses_valid_authored_artifacts(
        self, validate_mock, pipeline_mock, author_mock, render_mock
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "transcript.txt"
            transcript.write_text(
                "00:00 enough transcript material to pass the ingestion gate safely",
                encoding="utf-8",
            )
            pipeline_mock.return_value = {
                "video_id": "dQw4w9WgXcQ",
                "title": "Reusable Sample",
                "duration_seconds": 180.0,
                "transcript_txt": transcript,
                "transcript_json": None,
                "transcript_with_frames": None,
                "frames_dir": None,
                "frames_index": None,
                "transcript_provider": "youtube_transcript_api",
            }
            validate_mock.return_value = (
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
            )
            author_mock.return_value = "# Reusable\n\n" + (
                "Substantial verified study material. " * 20
            )
            render_mock.side_effect = lambda *args, **kwargs: _write_test_pdf(args[1])

            first = run_url_job(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                work_root=root,
                use_cached_pipeline=False,
                progress=False,
            )
            second = run_url_job(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                work_root=root,
                use_cached_pipeline=False,
                progress=False,
            )

            Path(second["markdown_path"]).write_text(
                "# Revised\n\n" + ("Changed but valid study material. " * 20),
                encoding="utf-8",
            )
            third = run_url_job(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                work_root=root,
                use_cached_pipeline=False,
                progress=False,
            )

        self.assertEqual(first["pdf_path"], second["pdf_path"])
        self.assertEqual(second["pdf_path"], third["pdf_path"])
        # A tampered markdown file invalidates the author-stage hash. The
        # deterministic replacement matches the already validated PDF hash,
        # so authoring repeats but rendering need not.
        self.assertEqual(author_mock.call_count, 2)
        self.assertEqual(render_mock.call_count, 1)
        self.assertEqual(pipeline_mock.call_count, 3)


if __name__ == "__main__":
    unittest.main()
