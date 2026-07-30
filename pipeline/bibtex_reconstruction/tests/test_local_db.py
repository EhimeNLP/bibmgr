from __future__ import annotations

from unittest import mock

import pytest

from bibtex_reconstruction.clients.local_db import LocalDBClient
from bibtex_reconstruction.config import settings
from bibtex_reconstruction.domain import InputData, ReferenceData


def reference() -> InputData:
    return InputData(
        parsed_data=ReferenceData(
            id="b1",
            title="A Stored Reference",
            authors=["Doe, Jane"],
            year="2024",
            doi="10.1000/stored",
            raw_text="Doe. A Stored Reference. 2024.",
        )
    )


def test_local_db_returns_the_stored_source_without_reformatting(monkeypatch):
    response = mock.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "items": [
            {
                "title": "A Stored Reference",
                "authors": ["Doe, Jane"],
                "year": 2024,
                "venue": "Journal of Tests",
                "doi": "10.1000/stored",
                "url": "https://example.test/stored",
                "bibtex": "@article{StoredKey, title={A Stored Reference}}",
            }
        ]
    }
    request = mock.Mock(return_value=response)
    monkeypatch.setattr(
        "bibtex_reconstruction.clients.local_db.requests.get",
        request,
    )
    monkeypatch.setattr(settings, "localdb_cookie", "bibmgr_session=secret")

    metadata, bibtex = LocalDBClient().search(reference())

    assert metadata is not None
    assert metadata.doi == "10.1000/stored"
    assert bibtex == "@article{StoredKey, title={A Stored Reference}}"
    assert request.call_args.kwargs["headers"] == {
        "Cookie": "bibmgr_session=secret"
    }
    assert request.call_args.kwargs["params"]["identifier"] == (
        "10.1000/stored"
    )


def test_local_db_can_search_by_doi_without_a_title(monkeypatch):
    response = mock.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "items": [
            {
                "title": "A Stored Reference",
                "authors": ["Doe, Jane"],
                "year": 2024,
                "doi": "10.1000/stored",
                "bibtex": "@misc{StoredKey, title={A Stored Reference}}",
            }
        ]
    }
    request = mock.Mock(return_value=response)
    monkeypatch.setattr(
        "bibtex_reconstruction.clients.local_db.requests.get",
        request,
    )
    input_data = reference()
    input_data.parsed_data.title = None

    metadata, bibtex = LocalDBClient().search(input_data)

    assert metadata is not None
    assert bibtex is not None
    assert request.call_args.kwargs["params"]["query"] == ""
    assert request.call_args.kwargs["params"]["identifier"] == (
        "10.1000/stored"
    )


def test_local_db_rejects_plain_http_away_from_loopback(monkeypatch):
    monkeypatch.setattr(
        settings,
        "localdb_base_url",
        "http://bibmgr.example.test/references/page",
    )

    with pytest.raises(ValueError, match="loopback"):
        LocalDBClient().search(reference())
