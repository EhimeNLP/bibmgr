from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from bibmgr_slack.config import SettingsError, load_settings


def arguments(**values: object) -> Namespace:
    return Namespace(
        language=values.get("language"),
        profile_directory=values.get("profile_directory"),
    )


def test_reads_tokens_and_language_from_environment() -> None:
    settings = load_settings(
        arguments(),
        environ={
            "SLACK_APP_TOKEN": "xapp-test",
            "SLACK_BOT_TOKEN": "xoxb-test",
            "BIBMGR_SLACK_LANGUAGE": "ja",
            "BIBMGR_SLACK_PROFILE_DIR": "/profiles",
        },
        is_tty=False,
    )

    assert settings.language == "ja"
    assert settings.profile_directory == Path("/profiles")


def test_prompts_for_missing_tokens_on_a_tty_without_echo_contract() -> None:
    answers = iter(("xapp-interactive", "xoxb-interactive"))
    settings = load_settings(
        arguments(profile_directory=Path("/profiles")),
        environ={},
        is_tty=True,
        secret_input=lambda _prompt: next(answers),
    )

    assert settings.app_token == "xapp-interactive"
    assert settings.bot_token == "xoxb-interactive"
    assert settings.language == "en"


def test_requires_environment_tokens_without_a_tty() -> None:
    with pytest.raises(SettingsError):
        load_settings(arguments(), environ={}, is_tty=False)
