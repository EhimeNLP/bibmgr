from __future__ import annotations

import pytest

from bibmgr_slack.input import InputError, extract_bibtex


def test_extracts_unlabelled_code_block_without_requiring_a_language() -> None:
    source = extract_bibtex("<@U1> ```\n@misc{k, title={A &amp; B},}\n```")

    assert source == "@misc{k, title={A & B},}"


def test_accepts_optional_bibtex_label_for_compatibility() -> None:
    source = extract_bibtex("<@U1>\n```bibtex\n@misc{k,}\n```")

    assert source == "@misc{k,}"


@pytest.mark.parametrize("text", ["<@U1> @misc{k,}", "```a``` and ```b```"])
def test_requires_exactly_one_code_block(text: str) -> None:
    with pytest.raises(InputError):
        extract_bibtex(text)
