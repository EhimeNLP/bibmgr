"""Command-line entry point for packaged database migrations."""

from __future__ import annotations

import argparse
from importlib.resources import files
import os
from collections.abc import Callable

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from .database import database_url


LOCAL_RESET_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class ResetRefusedError(RuntimeError):
    """A destructive reset did not meet the development safety checks."""


def migration_config() -> Config:
    config = Config()
    migrations = files("bibmgr_backend").joinpath("migrations")
    config.set_main_option("script_location", str(migrations))
    config.set_main_option(
        "sqlalchemy.url", database_url().replace("%", "%%")
    )
    return config


def local_postgresql_target(url: str) -> URL:
    try:
        target = make_url(url)
    except ArgumentError as error:
        raise ResetRefusedError("The database URL is invalid.") from error
    if target.get_backend_name() != "postgresql":
        raise ResetRefusedError(
            "Reset is only supported for a PostgreSQL database."
        )
    if target.host not in LOCAL_RESET_HOSTS:
        raise ResetRefusedError(
            "Reset is restricted to PostgreSQL on localhost."
        )
    if not target.database:
        raise ResetRefusedError(
            "Reset requires an explicit database name."
        )
    return target


def reset_database(
    config: Config,
    *,
    assume_yes: bool,
    prompt: Callable[[str], str] = input,
) -> bool:
    target = local_postgresql_target(database_url())
    display_url = target.render_as_string(hide_password=True)

    if assume_yes:
        if os.environ.get("BIBMGR_ENV") != "development":
            raise ResetRefusedError(
                "--yes requires BIBMGR_ENV=development."
            )
    else:
        confirmation = prompt(
            "This deletes every bibmgr table and recreates it at the latest "
            f"revision.\nTarget: {display_url}\n"
            f"Type the database name `{target.database}` to continue: "
        )
        if confirmation != target.database:
            print("Database reset cancelled.")
            return False

    command.downgrade(config, "base")
    command.upgrade(config, "head")
    print(f"Database reset completed: {display_url}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Manage the bibmgr PostgreSQL schema."
    )
    parser.add_argument(
        "command",
        choices=("upgrade", "current", "check", "reset"),
        nargs="?",
        default="upgrade",
    )
    parser.add_argument(
        "revision",
        nargs="?",
        default="head",
        help="Target revision for upgrade (default: head).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Skip reset confirmation; requires "
            "BIBMGR_ENV=development."
        ),
    )
    arguments = parser.parse_args()
    if arguments.yes and arguments.command != "reset":
        parser.error("--yes is only valid with the reset command.")
    config = migration_config()

    try:
        if arguments.command == "upgrade":
            command.upgrade(config, arguments.revision)
        elif arguments.command == "current":
            command.current(config, verbose=True)
        elif arguments.command == "check":
            command.check(config)
        else:
            reset_database(config, assume_yes=arguments.yes)
    except ResetRefusedError as error:
        parser.error(str(error))


if __name__ == "__main__":  # pragma: no cover
    main()
