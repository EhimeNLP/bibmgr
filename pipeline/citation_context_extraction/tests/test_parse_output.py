import json
import tempfile
import unittest
from pathlib import Path

from paper_extractor.parse_output import main
from paper_extractor.heuristics import parse_reference_entry, split_reference_entries
from paper_extractor.summary import extract_essential_info, summarize_extraction


class ParseOutputTests(unittest.TestCase):
    def test_extract_essential_info_from_normalized_output(self) -> None:
        payload = {
            "metadata": {"title": "Paper", "authors": ["A"], "year": "2025", "doi": "10.1/x"},
            "references": [
                {"id": "b0", "title": "Ref", "authors": ["B"], "year": "2020", "doi": None, "raw_text": "B. Ref."}
            ],
        }
        essential = extract_essential_info(payload)
        self.assertEqual(essential["title"], "Paper")
        self.assertEqual(essential["reference_count"], 1)
        self.assertEqual(essential["references"][0]["title"], "Ref")

    def test_extract_essential_info_repairs_metadata_from_raw_layout(self) -> None:
        payload = {
            "metadata": {
                "title": "これは本文の一文でありタイトルではない．",
                "authors": [],
                "raw": {
                    "pages": [
                        {
                            "parsing_res_list": [
                                {
                                    "block_label": "doc_title",
                                    "block_content": "正しいタイトル",
                                    "block_order": 1,
                                },
                                {
                                    "block_label": "text",
                                    "block_content": "米山 瑛人 $ ^{1} $ 杉原 壮一郎 $ ^{1} $",
                                    "block_order": 2,
                                },
                            ]
                        }
                    ]
                },
            },
            "references": [],
        }
        essential = extract_essential_info(payload)
        self.assertEqual(essential["title"], "正しいタイトル")
        self.assertEqual(essential["authors"], ["米山 瑛人", "杉原 壮一郎"])

    def test_summary_formats(self) -> None:
        payload = {
            "metadata": {"title": "Paper", "authors": ["A"]},
            "references": [{"id": "b0", "title": "Ref", "authors": ["B"], "year": "2020"}],
        }
        self.assertIn("# Paper", summarize_extraction(payload, fmt="markdown"))
        self.assertIn("references: 1", summarize_extraction(payload, fmt="text"))
        self.assertIn("id,title,authors", summarize_extraction(payload, fmt="csv"))

    def test_reference_author_parser_stops_before_title_and_venue(self) -> None:
        reference = parse_reference_entry(
            "西原大貴, 梶原智之, 谷川千尋, 清水優仁, 長原一. "
            "矯正歯科治療における所見文書からの自動診断に向けて. "
            "情報処理学会第 83 回全国大会, pp. 591–592, 2021.",
            index=0,
            source="test",
            confidence=0.5,
        )
        self.assertEqual(reference.authors, ["西原大貴", "梶原智之", "谷川千尋", "清水優仁", "長原一"])
        self.assertEqual(reference.title, "矯正歯科治療における所見文書からの自動診断に向けて")
        self.assertNotIn("pp. 591–592", reference.authors)

    def test_summary_repairs_polluted_reference_authors_from_raw_text(self) -> None:
        payload = {
            "title": "Paper",
            "authors": ["A"],
            "references": [
                {
                    "id": "b0",
                    "authors": [
                        "Takumi Ohtsuka",
                        "and Takashi Ninomiya. Automated Orthodontic Diagnosis from a Summary of Medical Findings. "
                        "In Proceedings of the 5th Clinical Natural Language Processing Workshop",
                    ],
                    "raw_text": (
                        "Takumi Ohtsuka, Tomoyuki Kajiwara, and Takashi Ninomiya. "
                        "Automated Orthodontic Diagnosis from a Summary of Medical Findings. "
                        "In Proceedings of the 5th Clinical Natural Language Processing Workshop, pp. 156–160, 2023."
                    ),
                }
            ],
        }
        essential = extract_essential_info(payload)
        self.assertEqual(
            essential["references"][0]["authors"],
            ["Takumi Ohtsuka", "Tomoyuki Kajiwara", "Takashi Ninomiya"],
        )
        self.assertEqual(
            essential["references"][0]["title"],
            "Automated Orthodontic Diagnosis from a Summary of Medical Findings",
        )

    def test_split_unnumbered_acl_references(self) -> None:
        block = (
            "Francisca Adoma Acheampong, Chen Wenyu, and Henry Nunoo-Mensah. 2020. "
            "Text-based Emotion Detection: Advances, Challenges, and Opportunities. "
            "Engineering Reports, 2(7):1–24. "
            "Saima Aman and Stan Szpakowicz. 2007. Identifying Expressions of Emotion in Text. "
            "In International Conference on Text, Speech and Dialogue, pages 196–205. "
            "Piotr Bojanowski, Edouard Grave, Armand Joulin, and Tomas Mikolov. 2017. "
            "Enriching Word Vectors with Subword Information. "
            "Transactions of the Association for Computational Linguistics, 5:135–146."
        )
        entries = split_reference_entries(block)
        self.assertEqual(len(entries), 3)
        self.assertTrue(entries[1].startswith("Saima Aman"))

    def test_summary_expands_single_concatenated_reference(self) -> None:
        raw_text = (
            "Francisca Adoma Acheampong, Chen Wenyu, and Henry Nunoo-Mensah. 2020. "
            "Text-based Emotion Detection: Advances, Challenges, and Opportunities. "
            "Engineering Reports, 2(7):1–24. "
            "Saima Aman and Stan Szpakowicz. 2007. Identifying Expressions of Emotion in Text. "
            "In International Conference on Text, Speech and Dialogue, pages 196–205."
        )
        essential = extract_essential_info(
            {
                "title": "Paper",
                "authors": [],
                "references": [{"id": "b0", "raw_text": raw_text, "authors": ["polluted"], "year": "2020"}],
            }
        )
        self.assertEqual(essential["reference_count"], 2)
        self.assertEqual(essential["references"][0]["authors"][0], "Francisca Adoma Acheampong")
        self.assertEqual(essential["references"][1]["authors"], ["Saima Aman", "Stan Szpakowicz"])

    def test_parse_output_cli_writes_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = root / "out.json"
            input_path.write_text(
                json.dumps({"metadata": {"title": "Paper"}, "references": []}),
                encoding="utf-8",
            )
            output_path = root / "summary.md"
            exit_code = main([str(input_path), "--format", "markdown", "-o", str(output_path)])
            self.assertEqual(exit_code, 0)
            self.assertIn("# Paper", output_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
