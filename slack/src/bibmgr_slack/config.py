"""Startup configuration and interactive credential collection."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from getpass import getpass
import os
from pathlib import Path
import sys


class SettingsError(ValueError):
    """Raised when the Slack app cannot start with the supplied settings."""


@dataclass(frozen=True)
class Settings:
    app_token: str
    bot_token: str
    language: str
    profile_directory: Path
    request_ttl_seconds: int = 600
    max_input_bytes: int = 12_000


def argument_parser() -> ArgumentParser:
    parser = ArgumentParser(description="Run the BibMgR Slack app in Socket Mode.")
    parser.add_argument("--language", choices=("en", "ja"))
    parser.add_argument("--profile-directory", type=Path)
    return parser


def load_settings(
    arguments: Namespace,
    *,
    environ: Mapping[str, str] | None = None,
    is_tty: bool | None = None,
    secret_input: Callable[[str], str] = getpass,
) -> Settings:
    values = os.environ if environ is None else environ
    language = arguments.language or values.get("BIBMGR_SLACK_LANGUAGE", "en")
    if language not in {"en", "ja"}:
        raise SettingsError("BIBMGR_SLACK_LANGUAGE must be `en` or `ja`.")

    interactive = sys.stdin.isatty() if is_tty is None else is_tty
    app_token = values.get("SLACK_APP_TOKEN", "").strip()
    bot_token = values.get("SLACK_BOT_TOKEN", "").strip()
    if not app_token:
        app_token = _read_secret(
            "Slack App Token (xapp-): ",
            "Slack App Token（xapp-）: ",
            language,
            interactive,
            secret_input,
        )
    if not bot_token:
        bot_token = _read_secret(
            "Slack Bot Token (xoxb-): ",
            "Slack Bot Token（xoxb-）: ",
            language,
            interactive,
            secret_input,
        )
    if not app_token.startswith("xapp-"):
        raise SettingsError("SLACK_APP_TOKEN must start with `xapp-`.")
    if not bot_token.startswith("xoxb-"):
        raise SettingsError("SLACK_BOT_TOKEN must start with `xoxb-`.")

    profile_directory = arguments.profile_directory or Path(
        values.get(
            "BIBMGR_SLACK_PROFILE_DIR",
            "/opt/bibmgr-slack/export-profiles",
        )
    )
    request_ttl_seconds = _positive_integer(
        values, "BIBMGR_SLACK_REQUEST_TTL_SECONDS", 600
    )
    max_input_bytes = _positive_integer(
        values, "BIBMGR_SLACK_MAX_INPUT_BYTES", 12_000
    )
    return Settings(
        app_token=app_token,
        bot_token=bot_token,
        language=language,
        profile_directory=profile_directory,
        request_ttl_seconds=request_ttl_seconds,
        max_input_bytes=max_input_bytes,
    )


def _read_secret(
    english_prompt: str,
    japanese_prompt: str,
    language: str,
    interactive: bool,
    secret_input: Callable[[str], str],
) -> str:
    if not interactive:
        raise SettingsError(
            "SLACK_APP_TOKEN and SLACK_BOT_TOKEN are required when stdin is not a TTY."
        )
    return secret_input(japanese_prompt if language == "ja" else english_prompt).strip()


def _positive_integer(
    values: Mapping[str, str], name: str, default: int
) -> int:
    raw = values.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise SettingsError(f"{name} must be a positive integer.") from error
    if value <= 0:
        raise SettingsError(f"{name} must be a positive integer.")
    return value
