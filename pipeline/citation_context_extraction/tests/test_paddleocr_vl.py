import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from paper_extractor.paddleocr_vl import (
    _raise_if_gpu_paddle_without_cuda_device,
    _raise_if_requested_gpu_is_unavailable,
    parse_paddleocr_vl_payload,
    run_paddleocr_vl,
)


class PaddleOcrVlParsingTests(unittest.TestCase):
    def test_parse_paddleocr_vl_payload(self) -> None:
        metadata, references = parse_paddleocr_vl_payload(
            {
                "metadata": {
                    "title": "Vision Paper",
                    "authors": ["A. Researcher", "B. Scientist"],
                    "year": 2024,
                    "doi": "https://doi.org/10.7777/VISION",
                },
                "references": [
                    {
                        "id": "ref-1",
                        "raw_text": "Someone. 2020. Work.",
                        "title": "Work",
                        "authors": "Someone",
                        "year": "2020",
                        "venue": "Proceedings",
                    }
                ],
            }
        )
        self.assertEqual(metadata.title, "Vision Paper")
        self.assertEqual(metadata.authors, ["A. Researcher", "B. Scientist"])
        self.assertEqual(metadata.year, "2024")
        self.assertEqual(metadata.doi, "10.7777/vision")
        self.assertEqual(references[0].id, "ref-1")
        self.assertEqual(references[0].authors, ["Someone"])

    def test_parse_paddleocr_vl_payload_uses_layout_title_and_authors(self) -> None:
        metadata, _ = parse_paddleocr_vl_payload(
            {
                "pages": [
                    {
                        "page_index": 0,
                        "parsing_res_list": [
                            {
                                "block_label": "doc_title",
                                "block_content": "所見文書と X 線画像を用いた矯正歯科治療の自動診断",
                                "block_order": 1,
                            },
                            {
                                "block_label": "text",
                                "block_content": (
                                    "米山 瑛人 $ ^{1} $ 杉原 壮一郎 $ ^{1} $\n"
                                    "梶原 智之 $ ^{1,2} $ 池田 直樹 $ ^{2} $"
                                ),
                                "block_order": 2,
                            },
                            {"block_label": "text", "block_content": "1 愛媛大学  $ ^{2} $ 大阪大学", "block_order": 3},
                            {"block_label": "abstract", "block_content": "本研究では，概要を書く．", "block_order": 4},
                        ],
                    }
                ]
            }
        )
        self.assertEqual(metadata.title, "所見文書と X 線画像を用いた矯正歯科治療の自動診断")
        self.assertEqual(metadata.authors[:2], ["米山 瑛人", "杉原 壮一郎"])
        self.assertIn("梶原 智之", metadata.authors)
        self.assertEqual(metadata.abstract, "本研究では，概要を書く．")

    def test_parse_paddleocr_vl_payload_uses_english_author_lines_before_affiliations(self) -> None:
        metadata, _ = parse_paddleocr_vl_payload(
            {
                "pages": [
                    {
                        "page_index": 0,
                        "parsing_res_list": [
                            {"block_label": "doc_title", "block_content": "WRIME", "block_order": 1},
                            {
                                "block_label": "text",
                                "block_content": (
                                    "Tomoyuki Kajiwara\n"
                                    "Graduate School of Science and Engineering\n"
                                    "Ehime University, Japan\n"
                                    "kajiwara@cs.ehime-u.ac.jp\n"
                                    "Chenhui Chu"
                                ),
                                "block_order": 2,
                            },
                            {
                                "block_label": "text",
                                "block_content": (
                                    "Noriko Takemura Yuta Nakashima Hajime Nagahara\n"
                                    "Institute for Datability Science, Osaka University, Japan"
                                ),
                                "block_order": 3,
                            },
                            {"block_label": "abstract", "block_content": "Abstract.", "block_order": 4},
                        ],
                    }
                ]
            }
        )
        self.assertEqual(
            metadata.authors,
            ["Tomoyuki Kajiwara", "Chenhui Chu", "Noriko Takemura", "Yuta Nakashima", "Hajime Nagahara"],
        )

    def test_run_paddleocr_vl_uses_installed_library_prediction_text(self) -> None:
        class FakePipeline:
            def predict(self, input):
                return [
                    {
                        "text": """
                        Mocked OCR Paper
                        Abstract
                        Example.
                        References
                        [1] Doe, J. 2020. Mock Reference. Journal.
                        """
                    }
                ]

        with mock.patch.dict(
            "sys.modules",
            {"paddleocr": mock.Mock(PaddleOCRVL=mock.Mock(return_value=FakePipeline()))},
        ):
            metadata, references, saved_files = run_paddleocr_vl(Path("paper.pdf"))

        self.assertEqual(metadata.title, "Mocked OCR Paper")
        self.assertEqual(len(references), 1)
        self.assertEqual(references[0].source, "paddleocr-vl")
        self.assertEqual(saved_files, [])

    def test_run_paddleocr_vl_passes_service_options_and_restructures_pdf(self) -> None:
        class FakePipeline:
            init_kwargs = None
            restructured = False

            def __init__(self, **kwargs):
                FakePipeline.init_kwargs = kwargs

            def predict(self, input):
                return [{"text": "page one"}]

            def restructure_pages(self, pages):
                FakePipeline.restructured = True
                return [
                    {
                        "text": """
                        Service OCR Paper
                        Abstract
                        Example.
                        References
                        [1] Doe, J. 2021. Service Reference. Journal.
                        """
                    }
                ]

        with mock.patch.dict(
            "sys.modules",
            {"paddleocr": mock.Mock(PaddleOCRVL=FakePipeline)},
        ):
            metadata, references, saved_files = run_paddleocr_vl(
                Path("paper.pdf"),
                engine="transformers",
                vl_rec_backend="vllm-server",
                vl_rec_server_url="http://localhost:8118/v1",
                vl_rec_api_model_name="PaddlePaddle/PaddleOCR-VL-1.5",
            )

        self.assertEqual(FakePipeline.init_kwargs["engine"], "transformers")
        self.assertEqual(FakePipeline.init_kwargs["vl_rec_backend"], "vllm-server")
        self.assertTrue(FakePipeline.restructured)
        self.assertEqual(metadata.title, "Service OCR Paper")
        self.assertEqual(references[0].year, "2021")
        self.assertEqual(saved_files, [])

    def test_run_paddleocr_vl_saves_native_artifacts(self) -> None:
        class FakeResult:
            def __init__(self):
                self.json = {"text": "Saved Paper\nReferences\n[1] Doe, J. 2020. Ref."}

            def save_to_json(self, save_path):
                Path(save_path, "native.json").write_text(json.dumps(self.json), encoding="utf-8")

            def save_to_markdown(self, save_path):
                Path(save_path, "native.md").write_text("# Saved Paper\n", encoding="utf-8")

            def save_to_word(self, save_path):
                Path(save_path, "native.docx").write_bytes(b"word output should not be saved")

        class FakePipeline:
            def predict(self, input):
                return [FakeResult()]

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(
                "sys.modules",
                {"paddleocr": mock.Mock(PaddleOCRVL=mock.Mock(return_value=FakePipeline()))},
            ):
                metadata, references, saved_files = run_paddleocr_vl(Path("paper.pdf"), save_dir=Path(temp_dir))

            self.assertEqual(metadata.title, "Saved Paper")
            self.assertTrue(any(path.name == "native.json" for path in saved_files))
            self.assertTrue(any(path.name == "native.md" for path in saved_files))
            self.assertFalse(any(path.suffix == ".docx" for path in saved_files))
            self.assertFalse((Path(temp_dir) / "native.docx").exists())

    def test_run_paddleocr_vl_cudnn_failure_has_actionable_hint(self) -> None:
        class FakePipeline:
            def predict(self, input):
                raise RuntimeError("CUDNN_STATUS_EXECUTION_FAILED")

        with mock.patch.dict(
            "sys.modules",
            {"paddleocr": mock.Mock(PaddleOCRVL=mock.Mock(return_value=FakePipeline()))},
        ):
            with self.assertRaises(RuntimeError) as context:
                run_paddleocr_vl(Path("paper.pdf"))

        message = str(context.exception)
        self.assertIn("--paddleocr-vl-device cpu", message)
        self.assertIn("--vl-rec-backend vllm-server", message)

    def test_run_paddleocr_vl_cuda_no_device_failure_has_actionable_hint(self) -> None:
        class FakePipeline:
            def predict(self, input):
                raise RuntimeError("CUDA error(100), no CUDA-capable device is detected")

        with mock.patch.dict(
            "sys.modules",
            {"paddleocr": mock.Mock(PaddleOCRVL=mock.Mock(return_value=FakePipeline()))},
        ):
            with self.assertRaises(RuntimeError) as context:
                run_paddleocr_vl(Path("paper.pdf"), device="cpu")

        message = str(context.exception)
        self.assertIn("CPU PaddlePaddle environment", message)
        self.assertIn("CUDA_VISIBLE_DEVICES", message)

    def test_cpu_mode_rejects_gpu_paddle_without_visible_cuda_device(self) -> None:
        fake_paddle = mock.Mock()
        fake_paddle.is_compiled_with_cuda.return_value = True
        fake_paddle.device.cuda.device_count.return_value = 0

        with mock.patch.dict("sys.modules", {"paddle": fake_paddle}):
            with self.assertRaises(RuntimeError) as context:
                _raise_if_gpu_paddle_without_cuda_device()

        self.assertIn("GPU build", str(context.exception))
        self.assertIn("paddlepaddle==3.2.1", str(context.exception))

    def test_gpu_mode_rejects_missing_visible_cuda_device(self) -> None:
        fake_paddle = mock.Mock()
        fake_paddle.is_compiled_with_cuda.return_value = True
        fake_paddle.device.cuda.device_count.return_value = 0

        with mock.patch.dict("sys.modules", {"paddle": fake_paddle}):
            with self.assertRaises(RuntimeError) as context:
                _raise_if_requested_gpu_is_unavailable("gpu")

        self.assertIn("cannot see any CUDA-capable GPU", str(context.exception))
        self.assertIn("nvidia-smi", str(context.exception))


if __name__ == "__main__":
    unittest.main()
