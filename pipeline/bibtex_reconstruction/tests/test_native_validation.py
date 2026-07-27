from core.native_validation import NativeBibtexValidator


def test_native_validator_accepts_registration_ready_bibtex():
    source = """@article{example,
  author = {Doe, Jane},
  title = {Example},
  journal = {Journal of Tests},
  year = {2024}
}"""

    result = NativeBibtexValidator().validate(source)

    assert result.accepted is True
    assert result.source.startswith("@article{example,")
    assert "title = {Example}" in result.source


def test_native_validator_preserves_blocking_diagnostics():
    result = NativeBibtexValidator().validate("@article{broken")

    assert result.accepted is False
    assert result.diagnostics[0].code == "BIB-SYNTAX-103"
    assert result.diagnostics[0].blocking is True


def test_native_validator_normalizes_doi_bibtex_before_final_decision():
    source = (
        "@article{Atkins_2002, title={Selective anticancer drugs}, "
        "volume={1}, ISSN={1474-1784}, "
        "url={http://dx.doi.org/10.1038/nrd842}, "
        "DOI={10.1038/nrd842}, number={7}, "
        "journal={Nature Reviews Drug Discovery}, "
        "author={Atkins, Joshua H. and Gershell, Leland J.}, "
        "year={2002}, month=July, pages={491–492} }"
    )

    result = NativeBibtexValidator().validate(source)

    assert result.accepted is True
    assert result.source.startswith("@article{atkins-2002,")
    assert "month = {jul}" in result.source
    assert "LAB-KEY-002:0" in result.applied_fix_ids
