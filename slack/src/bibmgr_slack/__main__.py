"""Run BibMgR's Slack app."""

from __future__ import annotations

import logging

import bibmgr_native
from slack_bolt.adapter.socket_mode import SocketModeHandler

from .app import create_app
from .config import argument_parser, load_settings
from .profiles import load_profile_catalog


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    arguments = argument_parser().parse_args()
    settings = load_settings(arguments)
    profiles = load_profile_catalog(bibmgr_native, settings.profile_directory)
    app = create_app(settings, bibmgr_native, profiles)
    identity = app.client.auth_test()
    logging.getLogger("bibmgr_slack").info(
        "Starting Socket Mode for team_id=%s bot_user_id=%s profiles=%d language=%s",
        identity.get("team_id"),
        identity.get("user_id"),
        len(profiles.profiles),
        settings.language,
    )
    SocketModeHandler(app, settings.app_token).start()


if __name__ == "__main__":
    main()
