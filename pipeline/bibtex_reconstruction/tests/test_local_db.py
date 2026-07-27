import unittest
from unittest import mock

from api_clients.local_db import LocalDBClient
from core.config import settings
from models import InputData, ReferenceData


class LocalDbClientTests(unittest.TestCase):
    def test_local_db_uses_public_structured_search(self) -> None:
        response = mock.Mock()
        response.json.return_value = {
            "items": [
                {
                    "title": "A Retrieved Reference",
                    "authors": ["Example Author"],
                    "year": 2024,
                    "venue": "TACL",
                    "doi": "10.1000/example",
                    "url": "https://example.org/reference",
                    "bibtex": "@article{retrieved}",
                }
            ]
        }
        response.raise_for_status.return_value = None
        reference = InputData(
            parsed_data=ReferenceData(
                id="ref-1",
                title="A Retrieved Reference",
                authors=["Example Author"],
                year="2024",
                raw_text="Example Author. A Retrieved Reference.",
                citation_contexts=["This work is cited here."],
            )
        )

        with (
            mock.patch.object(
                settings,
                "localdb_base_url",
                "http://127.0.0.1:8000/references/page",
            ),
            mock.patch.object(settings, "similarity_threshold", 0.95),
            mock.patch(
                "api_clients.local_db.requests.get",
                return_value=response,
            ) as request,
        ):
            metadata, bibtex = LocalDBClient()._execute_search(reference)

        self.assertIsNotNone(metadata)
        assert metadata is not None
        self.assertEqual(metadata.title, "A Retrieved Reference")
        self.assertEqual(bibtex, "@article{retrieved}")
        self.assertEqual(
            request.call_args.kwargs["params"],
            {
                "query": "A Retrieved Reference",
                "author": "Example Author",
                "year": "2024",
                "limit": 10,
                "offset": 0,
            },
        )
        self.assertEqual(
            request.call_args.kwargs["timeout"],
            settings.localdb_timeout,
        )

    def test_local_db_rejects_plain_http_off_loopback(self) -> None:
        reference = InputData(
            parsed_data=ReferenceData(
                id="ref-1",
                title="Reference",
                raw_text="Reference",
            )
        )

        with (
            mock.patch.object(
                settings,
                "localdb_base_url",
                "http://bibmgr.example.edu/api/references/page",
            ),
            self.assertRaisesRegex(ValueError, "loopback"),
        ):
            LocalDBClient()._execute_search(reference)


if __name__ == "__main__":
    unittest.main()
