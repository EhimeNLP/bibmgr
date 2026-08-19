import threading
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from paper_extractor.extractors import (
    ExtractionConfig,
    ExtractionError,
    extract_paper,
    extract_papers,
)
from paper_extractor.models import ExtractionResult, PaperMetadata


class BatchExtractionTests(unittest.TestCase):
    def test_extract_papers_runs_concurrently_and_preserves_input_order(self) -> None:
        pdfs = [Path("first.pdf"), Path("second.pdf")]
        both_started = threading.Barrier(2)

        def fake_extract(pdf: Path, *, config: ExtractionConfig) -> ExtractionResult:
            both_started.wait(timeout=2)
            return ExtractionResult(
                input_pdf=pdf,
                metadata=PaperMetadata(title=pdf.stem),
                references=[],
            )

        with mock.patch("paper_extractor.extractors.extract_paper", side_effect=fake_extract):
            results = extract_papers(pdfs, jobs=2)

        self.assertEqual([result.input_pdf for result in results], pdfs)
        self.assertEqual([result.metadata.title for result in results], ["first", "second"])

    def test_extract_papers_isolates_batch_save_directories(self) -> None:
        pdfs = [Path("first.pdf"), Path("second.pdf")]
        observed: dict[Path, Path | None] = {}
        observed_lock = threading.Lock()

        def fake_extract(pdf: Path, *, config: ExtractionConfig) -> ExtractionResult:
            with observed_lock:
                observed[pdf] = config.save_dir
            return ExtractionResult(
                input_pdf=pdf,
                metadata=PaperMetadata(),
                references=[],
            )

        config = ExtractionConfig(save_dir=Path("artifacts"))
        with mock.patch("paper_extractor.extractors.extract_paper", side_effect=fake_extract):
            extract_papers(pdfs, config=config, jobs=2)

        self.assertEqual(
            observed,
            {
                Path("first.pdf"): Path("artifacts/first"),
                Path("second.pdf"): Path("artifacts/second"),
            },
        )

    def test_extract_papers_reports_all_failures_in_input_order(self) -> None:
        pdfs = [Path("first.pdf"), Path("second.pdf")]

        def fake_extract(pdf: Path, *, config: ExtractionConfig) -> ExtractionResult:
            raise ExtractionError(f"cannot extract {pdf.name}")

        with (
            mock.patch("paper_extractor.extractors.extract_paper", side_effect=fake_extract),
            self.assertRaises(ExtractionError) as raised,
        ):
            extract_papers(pdfs, jobs=2)

        message = str(raised.exception)
        self.assertIn("Extraction failed for 2 PDF(s)", message)
        self.assertLess(message.index("first.pdf"), message.index("second.pdf"))

    def test_extract_papers_rejects_duplicate_stems_with_save_dir(self) -> None:
        config = ExtractionConfig(save_dir=Path("artifacts"))

        with self.assertRaises(ExtractionError) as raised:
            extract_papers([Path("a/paper.pdf"), Path("b/paper.pdf")], config=config)

        self.assertIn("unique file stems", str(raised.exception))

    def test_extract_papers_rejects_shared_artifact_for_batch(self) -> None:
        config = ExtractionConfig(paddleocr_vl_json=Path("artifact.json"))

        with self.assertRaises(ExtractionError) as raised:
            extract_papers([Path("first.pdf"), Path("second.pdf")], config=config)

        self.assertIn("can only be used with one PDF", str(raised.exception))

    def test_extract_paper_wraps_normalized_output_write_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = Path(temp_dir) / "paper.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            config = ExtractionConfig(save_dir=Path(temp_dir) / "artifacts")
            extracted = (PaperMetadata(), [], [])

            with (
                mock.patch("paper_extractor.extractors._extract_paddleocr_vl", return_value=extracted),
                mock.patch(
                    "paper_extractor.extractors._write_normalized_output",
                    side_effect=OSError("read-only file system"),
                ),
                self.assertRaises(ExtractionError) as raised,
            ):
                extract_paper(pdf, config=config)

        self.assertIn("Could not save extraction files", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
