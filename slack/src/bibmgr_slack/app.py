"""Bolt handlers for mention-driven BibTeX export."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Protocol

from slack_bolt import App

from .config import Settings
from .i18n import Translator
from .input import InputError, extract_bibtex
from .profiles import ProfileCatalog, ProfileSpec
from .state import PendingExport, PendingStore


ACTION_ID = "bibmgr_export_profile"
BLOCK_PREFIX = "bibmgr_profile:"
MAX_REPORTED_FINDINGS = 8


class NativeEngine(Protocol):
    def analyze(self, source: str, **kwargs: Any) -> Any: ...

    def export_source_workflow(self, source: str, **kwargs: Any) -> Any: ...


@dataclass
class BibmgrSlackBot:
    settings: Settings
    engine: NativeEngine
    profiles: ProfileCatalog
    pending: PendingStore
    translator: Translator
    logger: logging.Logger

    def register(self, app: App) -> None:
        app.event("app_mention")(self.handle_mention)
        app.action(ACTION_ID)(self.handle_profile_selection)

    def handle_mention(
        self,
        *,
        event: dict[str, Any],
        body: dict[str, Any],
        client: Any,
        **_: Any,
    ) -> None:
        event_id = str(
            body.get("event_id")
            or f"{body.get('team_id', '')}:{event.get('event_ts', event.get('ts', ''))}"
        )
        if not self.pending.mark_event(event_id):
            return
        channel_id = str(event["channel"])
        thread_ts = str(event.get("thread_ts") or event["ts"])
        user_id = str(event["user"])
        try:
            source = extract_bibtex(str(event.get("text", "")))
        except InputError:
            self._post_plain(client, channel_id, thread_ts, self.translator.text("usage"))
            return
        source_bytes = len(source.encode("utf-8"))
        if source_bytes > self.settings.max_input_bytes:
            self._post_plain(
                client,
                channel_id,
                thread_ts,
                self.translator.text(
                    "input_too_large", limit=self.settings.max_input_bytes
                ),
            )
            return

        try:
            analysis = self.engine.analyze(
                source,
                profile="modern",
                mode="strict",
            ).to_dict()
        except Exception as error:
            self.logger.error("BibTeX preflight failed (%s)", type(error).__name__)
            self._post_plain(
                client,
                channel_id,
                thread_ts,
                self.translator.text("export_failed"),
            )
            return
        if analysis.get("syntax", {}).get("status") != "ok":
            codes = sorted(
                {
                    str(item.get("code"))
                    for item in analysis.get("diagnostics", [])
                    if item.get("severity") == "error" and item.get("code")
                }
            )
            suffix = f" ({', '.join(codes)})" if codes else ""
            self._post_plain(
                client,
                channel_id,
                thread_ts,
                self.translator.text("invalid_syntax", codes=suffix),
            )
            return
        record_count = len(analysis.get("bibliography", {}).get("records", []))
        if record_count != 1:
            self._post_plain(
                client,
                channel_id,
                thread_ts,
                self.translator.text("record_count", count=record_count),
            )
            return

        request_id = self.pending.create(
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            source=source,
        )
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=self.translator.text("choose_profile"),
            blocks=[self._profile_selection_block(request_id)],
            mrkdwn=False,
            unfurl_links=False,
            unfurl_media=False,
        )

    def handle_profile_selection(
        self,
        *,
        ack: Any,
        body: dict[str, Any],
        client: Any,
        **_: Any,
    ) -> None:
        ack()
        user_id = str(body.get("user", {}).get("id", ""))
        action = body.get("actions", [{}])[0]
        block_id = str(action.get("block_id", ""))
        request_id = block_id.removeprefix(BLOCK_PREFIX)
        profile_id = str(action.get("selected_option", {}).get("value", ""))
        status, pending = self.pending.consume(request_id, user_id)
        if status != "ok" or pending is None:
            self._post_ephemeral(
                client,
                body,
                user_id,
                self.translator.text(status),
            )
            return
        profile = self.profiles.by_id(profile_id)
        if profile is None:
            self._post_plain(
                client,
                pending.channel_id,
                pending.thread_ts,
                self.translator.text("unknown_profile"),
            )
            return
        self._export(client, pending, profile)

    def _export(
        self, client: Any, pending: PendingExport, profile: ProfileSpec
    ) -> None:
        kwargs: dict[str, Any] = {"profile": profile.id}
        if profile.profile_json is not None:
            kwargs["profile_json"] = profile.profile_json
        try:
            result = self.engine.export_source_workflow(
                pending.source, **kwargs
            ).to_dict()
        except Exception as error:
            self.logger.error("BibTeX export failed (%s)", type(error).__name__)
            self._post_plain(
                client,
                pending.channel_id,
                pending.thread_ts,
                self.translator.text("export_failed"),
            )
            return

        client.chat_postMessage(
            channel=pending.channel_id,
            thread_ts=pending.thread_ts,
            text=self.translator.text("exported", profile=profile.id),
            blocks=self._result_blocks(result, profile.id),
            mrkdwn=False,
            unfurl_links=False,
            unfurl_media=False,
        )

    def _profile_selection_block(self, request_id: str) -> dict[str, Any]:
        return {
            "type": "section",
            "block_id": f"{BLOCK_PREFIX}{request_id}",
            "text": {
                "type": "plain_text",
                "text": self.translator.text("choose_profile"),
            },
            "accessory": {
                "type": "static_select",
                "action_id": ACTION_ID,
                "placeholder": {
                    "type": "plain_text",
                    "text": self.translator.text("choose_placeholder"),
                },
                "options": [
                    profile.option(self.settings.language)
                    for profile in self.profiles.profiles
                ],
            },
        }

    def _result_blocks(
        self, result: dict[str, Any], profile_id: str
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = [
            {
                "type": "section",
                "text": {
                    "type": "plain_text",
                    "text": self.translator.text("exported", profile=profile_id),
                },
            },
            {
                "type": "rich_text",
                "elements": [
                    {
                        "type": "rich_text_preformatted",
                        "elements": [
                            {"type": "text", "text": str(result.get("source", ""))}
                        ],
                        "border": 0,
                    }
                ],
            },
        ]
        summary = self._result_summary(result)
        if summary:
            blocks.append(
                {
                    "type": "section",
                    "text": {"type": "plain_text", "text": summary[:3000]},
                }
            )
        return blocks

    def _result_summary(self, result: dict[str, Any]) -> str:
        lines: list[str] = []
        fix_count = len(result.get("input_applied_fix_ids", [])) + len(
            result.get("output_applied_fix_ids", [])
        )
        if fix_count:
            lines.append(self.translator.text("fixes", count=fix_count))

        diagnostics = _unique_diagnostics(
            result.get("input_diagnostics", [])
            + result.get("output_diagnostics", [])
        )
        if diagnostics:
            lines.append(self.translator.text("remaining", count=len(diagnostics)))
            lines.extend(
                f"• {self.translator.diagnostic(item)}"
                for item in diagnostics[:MAX_REPORTED_FINDINGS]
            )

        warnings = result.get("warnings", [])
        if warnings:
            lines.append(
                self.translator.text("serializer_warnings", count=len(warnings))
            )
            lines.extend(
                f"• {self.translator.export_warning(item)}"
                for item in warnings[:MAX_REPORTED_FINDINGS]
            )
        return "\n".join(lines)

    @staticmethod
    def _post_plain(client: Any, channel: str, thread_ts: str, text: str) -> None:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=text,
            mrkdwn=False,
            unfurl_links=False,
            unfurl_media=False,
        )

    @staticmethod
    def _post_ephemeral(
        client: Any, body: dict[str, Any], user_id: str, text: str
    ) -> None:
        channel_id = str(
            body.get("channel", {}).get("id")
            or body.get("container", {}).get("channel_id")
            or ""
        )
        if channel_id:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=text,
                mrkdwn=False,
            )


def _unique_diagnostics(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str, bool]] = set()
    for item in items:
        key = (
            str(item.get("code", "")),
            str(item.get("message", "")),
            bool(item.get("blocking", False)),
        )
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def create_app(
    settings: Settings,
    engine: NativeEngine,
    profiles: ProfileCatalog,
) -> App:
    app = App(token=settings.bot_token)
    bot = BibmgrSlackBot(
        settings=settings,
        engine=engine,
        profiles=profiles,
        pending=PendingStore(settings.request_ttl_seconds),
        translator=Translator(settings.language),
        logger=logging.getLogger("bibmgr_slack"),
    )
    bot.register(app)
    return app
