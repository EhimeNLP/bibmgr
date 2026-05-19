import json
import tempfile
import unittest
from pathlib import Path

from paper_extractor.cli import main


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


if __name__ == "__main__":
    unittest.main()
