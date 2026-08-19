from __future__ import annotations

import pytest

from bibmgr_slack.input import InputError, extract_bibtex


def test_extracts_unlabelled_code_block_without_requiring_a_language() -> None:
    source = extract_bibtex("<@U1> ```\n@misc{k, title={A &amp; B},}\n```")

    assert source == "@misc{k, title={A & B},}"


def test_accepts_optional_bibtex_label_for_compatibility() -> None:
    source = extract_bibtex("<@U1>\n```bibtex\n@misc{k,}\n```")

    assert source == "@misc{k,}"


@pytest.mark.parametrize(
    ("slack_url", "expected_url"),
    [
        (
            "<https://arxiv.org/abs/2207.03960>",
            "https://arxiv.org/abs/2207.03960",
        ),
        (
            "<https://example.com/paper?lang=en&amp;format=pdf|download>",
            "https://example.com/paper?lang=en&format=pdf",
        ),
    ],
)
def test_restores_slack_auto_formatted_urls(slack_url: str, expected_url: str) -> None:
    source = extract_bibtex(
        f"```\n@misc{{k, url={{{slack_url}}},}}\n```"
    )

    assert source == f"@misc{{k, url={{{expected_url}}},}}"


def test_preserves_angle_brackets_that_are_not_slack_urls() -> None:
    source = extract_bibtex(
        "```\n@misc{k, title={A &lt; B, <not-a-url>, &lt;https://example.com&gt;},}\n```"
    )

    assert source == (
        "@misc{k, title={A < B, <not-a-url>, <https://example.com>},}"
    )


@pytest.mark.parametrize("text", ["<@U1> @misc{k,}", "```a``` and ```b```"])
def test_requires_exactly_one_code_block(text: str) -> None:
    with pytest.raises(InputError):
        extract_bibtex(text)
