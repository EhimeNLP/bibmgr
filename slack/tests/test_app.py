from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from slack_bolt.util.utils import get_arg_names_of_callable

from bibmgr_slack.app import BibmgrSlackBot
from bibmgr_slack.config import Settings
from bibmgr_slack.i18n import Translator
from bibmgr_slack.profiles import ProfileCatalog, ProfileSpec
from bibmgr_slack.state import PendingStore


class Dto:
    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    def to_dict(self) -> dict[str, Any]:
        return self.value


class Engine:
    def __init__(self, *, syntax_status: str = "ok") -> None:
        self.syntax_status = syntax_status
        self.workflow_calls: list[tuple[str, dict[str, Any]]] = []

    def analyze(self, _source: str, **_kwargs: Any) -> Dto:
        return Dto(
            {
                "syntax": {"status": self.syntax_status},
                "bibliography": {"records": [{}] if self.syntax_status == "ok" else []},
                "diagnostics": [
                    {
                        "code": "BIB-SYNTAX-103",
                        "severity": "error",
                        "message": "missing separator",
                    }
                ]
                if self.syntax_status != "ok"
                else [],
            }
        )

    def export_source_workflow(self, source: str, **kwargs: Any) -> Dto:
        self.workflow_calls.append((source, kwargs))
        return Dto(
            {
                "source": "@misc{k,\n  title = {T},\n}\n",
                "input_applied_fix_ids": ["BIB-SYNTAX-002:0"],
                "output_applied_fix_ids": [],
                "input_diagnostics": [
                    {
                        "code": "LAB-ENTRY-003",
                        "message": "required fields are missing",
                        "blocking": True,
                    }
                ],
                "output_diagnostics": [],
                "warnings": [],
            }
        )


class Client:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.ephemeral: list[dict[str, Any]] = []

    def chat_postMessage(self, **kwargs: Any) -> None:
        self.messages.append(kwargs)

    def chat_postEphemeral(self, **kwargs: Any) -> None:
        self.ephemeral.append(kwargs)


def bot(engine: Engine, language: str = "en") -> BibmgrSlackBot:
    settings = Settings(
        app_token="xapp-test",
        bot_token="xoxb-test",
        language=language,
        profile_directory=Path("/profiles"),
    )
    return BibmgrSlackBot(
        settings=settings,
        engine=engine,
        profiles=ProfileCatalog(
            (
                ProfileSpec(
                    id="modern",
                    display_name="Modern",
                    description="Modern",
                    validation_profile="modern",
                ),
            )
        ),
        pending=PendingStore(600),
        translator=Translator(language),
        logger=logging.getLogger("test"),
    )


def mention_payload() -> tuple[dict[str, Any], dict[str, Any]]:
    event = {
        "channel": "C1",
        "user": "U1",
        "ts": "1.0",
        "event_ts": "1.0",
        "text": "<@UBOT> ```\n@misc{k, title={T},}\n```",
    }
    return event, {"event_id": "Ev1", "team_id": "T1"}


def direct_message_payload() -> tuple[dict[str, Any], dict[str, Any]]:
    event = {
        "channel": "D1",
        "channel_type": "im",
        "user": "U1",
        "ts": "2.0",
        "event_ts": "2.0",
        "text": "```\n@misc{k, title={T},}\n```",
    }
    return event, {"event_id": "Ev2", "team_id": "T1"}


def test_handlers_expose_arguments_for_bolt_injection() -> None:
    service = bot(Engine())

    assert get_arg_names_of_callable(service.handle_mention) == [
        "self",
        "event",
        "body",
        "client",
    ]
    assert get_arg_names_of_callable(service.handle_profile_selection) == [
        "self",
        "ack",
        "body",
        "client",
    ]
    assert get_arg_names_of_callable(service.handle_direct_message) == [
        "self",
        "event",
        "body",
        "client",
    ]


def test_mention_then_selection_exports_in_the_original_thread() -> None:
    engine = Engine()
    service = bot(engine)
    client = Client()
    event, body = mention_payload()
    service.handle_mention(event=event, body=body, client=client)
    selection = client.messages[0]
    block_id = selection["blocks"][0]["block_id"]
    acknowledged: list[bool] = []

    service.handle_profile_selection(
        ack=lambda: acknowledged.append(True),
        body={
            "user": {"id": "U1"},
            "channel": {"id": "C1"},
            "actions": [
                {
                    "block_id": block_id,
                    "selected_option": {"value": "modern"},
                }
            ],
        },
        client=client,
    )

    assert acknowledged == [True]
    assert engine.workflow_calls[0][1]["profile"] == "modern"
    assert client.messages[-1]["thread_ts"] == "1.0"
    assert client.messages[-1]["mrkdwn"] is True
    assert client.messages[-1]["blocks"][0] == {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "Exported with the `modern` profile.",
        },
    }
    assert client.messages[-1]["blocks"][1]["type"] == "rich_text"


def test_direct_message_then_selection_exports_without_a_thread() -> None:
    engine = Engine()
    service = bot(engine)
    client = Client()
    event, body = direct_message_payload()

    service.handle_direct_message(event=event, body=body, client=client)

    selection = client.messages[0]
    assert "thread_ts" not in selection
    block_id = selection["blocks"][0]["block_id"]
    service.handle_profile_selection(
        ack=lambda: None,
        body={
            "user": {"id": "U1"},
            "channel": {"id": "D1"},
            "actions": [
                {
                    "block_id": block_id,
                    "selected_option": {"value": "modern"},
                }
            ],
        },
        client=client,
    )

    assert engine.workflow_calls[0][1]["profile"] == "modern"
    assert "thread_ts" not in client.messages[-1]
    assert client.messages[-1]["blocks"][1]["type"] == "rich_text"


def test_direct_message_ignores_non_user_message_events() -> None:
    ignored_events = (
        {"bot_id": "B1"},
        {"subtype": "message_changed"},
        {"channel_type": "channel"},
        {"user": ""},
    )

    for index, overrides in enumerate(ignored_events):
        service = bot(Engine())
        client = Client()
        event, body = direct_message_payload()
        event.update(overrides)
        body["event_id"] = f"ignored-{index}"

        service.handle_direct_message(event=event, body=body, client=client)

        assert client.messages == []


def test_direct_message_usage_does_not_request_a_mention() -> None:
    service = bot(Engine())
    client = Client()
    event, body = direct_message_payload()
    event["text"] = "not a code block"

    service.handle_direct_message(event=event, body=body, client=client)

    assert client.messages[0]["text"].startswith("Send exactly one BibTeX entry")
    assert "thread_ts" not in client.messages[0]


def test_expired_direct_message_selection_uses_a_regular_reply() -> None:
    service = bot(Engine())
    client = Client()

    service.handle_profile_selection(
        ack=lambda: None,
        body={
            "user": {"id": "U1"},
            "container": {"channel_id": "D1"},
            "actions": [
                {
                    "block_id": "bibmgr_profile:expired",
                    "selected_option": {"value": "modern"},
                }
            ],
        },
        client=client,
    )

    assert client.ephemeral == []
    assert client.messages[0]["channel"] == "D1"
    assert client.messages[0]["text"].startswith("This export request has expired")
    assert "thread_ts" not in client.messages[0]


def test_japanese_mode_does_not_expose_english_core_diagnostic_text() -> None:
    service = bot(Engine(), language="ja")
    summary = service._result_summary(  # noqa: SLF001 - formatting is the unit under test
        {
            "input_applied_fix_ids": [],
            "output_applied_fix_ids": [],
            "input_diagnostics": [
                {
                    "code": "LAB-ENTRY-003",
                    "message": "required fields are missing",
                    "blocking": True,
                }
            ],
            "output_diagnostics": [],
            "warnings": [{"message": "only the first URL was exported"}],
        }
    )

    assert "required fields are missing" not in summary
    assert "only the first URL was exported" not in summary
    assert "未解決" in summary
    assert "エントリ種別に応じた必須フィールドが不足しています。" in summary


def test_japanese_mode_explains_the_malformed_absolute_url_rule() -> None:
    service = bot(Engine(), language="ja")

    summary = service._result_summary(  # noqa: SLF001 - formatting is the unit under test
        {
            "input_applied_fix_ids": [],
            "output_applied_fix_ids": [],
            "input_diagnostics": [
                {
                    "code": "BIB-SEMANTIC-106",
                    "message": "invalid absolute URL: example.com/paper",
                    "blocking": True,
                }
            ],
            "output_diagnostics": [],
            "warnings": [],
        }
    )

    assert "invalid absolute URL" not in summary
    assert (
        "[BIB-SEMANTIC-106] "
        "URLはhttp://またはhttps://で始まる有効な絶対URLである必要があります。"
        in summary
    )


def test_invalid_syntax_is_reported_before_profile_selection() -> None:
    service = bot(Engine(syntax_status="failed"))
    client = Client()
    event, body = mention_payload()

    service.handle_mention(event=event, body=body, client=client)

    assert len(client.messages) == 1
    assert "not valid BibTeX" in client.messages[0]["text"]
    assert "blocks" not in client.messages[0]
