import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from paper_extractor.cli import main
from paper_extractor.models import ExtractionResult, PaperMetadata


class CliTests(unittest.TestCase):
    def test_cli_writes_json_file_from_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf = root / "paper.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            artifact = root / "paper.vlm.json"
            artifact.write_text(
                json.dumps({"metadata": {"title": "Artifact Paper"}, "references": ["Raw reference."]}),
                encoding="utf-8",
            )
            output = root / "out.json"
            exit_code = main(
                [
                    str(pdf),
                    "--paddleocr-vl-json",
                    str(artifact),
                    "-o",
                    str(output),
                ]
            )
            self.assertEqual(exit_code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["metadata"]["title"], "Artifact Paper")
            self.assertEqual(payload["engine"], "paddleocr-vl")
            self.assertEqual(payload["references"][0]["source"], "paddleocr-vl")

    def test_cli_emits_ordered_json_array_for_batch(self) -> None:
        pdfs = [Path("first.pdf"), Path("second.pdf")]
        results = [
            ExtractionResult(
                input_pdf=pdf,
                metadata=PaperMetadata(title=pdf.stem),
                references=[],
            )
            for pdf in pdfs
        ]
        stdout = io.StringIO()
        with (
            mock.patch("paper_extractor.cli.extract_papers", return_value=results) as extract,
            redirect_stdout(stdout),
        ):
            exit_code = main([*(str(pdf) for pdf in pdfs), "--jobs", "3"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual([document["input_pdf"] for document in payload], [str(pdf) for pdf in pdfs])
        self.assertEqual([document["metadata"]["title"] for document in payload], ["first", "second"])
        self.assertEqual(extract.call_args.kwargs["jobs"], 3)

    def test_cli_rejects_single_output_path_for_batch(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            main(["first.pdf", "second.pdf", "--output", "output.json"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--output can only be used with one PDF", stderr.getvalue())

    def test_cli_rejects_non_positive_jobs(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            main(["paper.pdf", "--jobs", "0"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("must be at least 1", stderr.getvalue())

    def test_cli_reports_unwritable_output_without_traceback(self) -> None:
        result = ExtractionResult(
            input_pdf=Path("paper.pdf"),
            metadata=PaperMetadata(),
            references=[],
        )
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_directory = Path(temp_dir) / "output.json"
            output_directory.mkdir()
            with (
                mock.patch("paper_extractor.cli.extract_papers", return_value=[result]),
                redirect_stderr(stderr),
                self.assertRaises(SystemExit) as raised,
            ):
                main(["paper.pdf", "--output", str(output_directory)])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("Could not write output", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
