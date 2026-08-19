"""Operational backup and restore commands for the PostgreSQL database."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from sqlalchemy.engine import URL, make_url

from .database import database_url


def backup_database(
    *,
    url: str,
    output_directory: Path,
    now: datetime | None = None,
) -> Path:
    database = _postgres_url(url)
    pg_dump = _required_executable("pg_dump")
    output_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    destination = output_directory / f"{database.database}-{timestamp}.dump"
    temporary = output_directory / f".{destination.name}.{uuid.uuid4().hex}.partial"

    command = [
        pg_dump,
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        f"--file={temporary}",
        *_connection_arguments(database),
    ]
    try:
        _run(command, database)
        temporary.chmod(0o600)
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def restore_database(
    *,
    url: str,
    input_path: Path,
    confirmed_database: str,
) -> None:
    database = _postgres_url(url)
    if confirmed_database != database.database:
        raise ValueError(
            "Restore confirmation must exactly match the target database name "
            f"({database.database})."
        )
    if not input_path.is_file():
        raise FileNotFoundError(f"Backup file does not exist: {input_path}")

    pg_restore = _required_executable("pg_restore")
    command = [
        pg_restore,
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-privileges",
        "--exit-on-error",
        *_connection_arguments(database),
        str(input_path),
    ]
    _run(command, database)


def _postgres_url(value: str) -> URL:
    parsed = make_url(value)
    if parsed.get_backend_name() != "postgresql" or not parsed.database:
        raise ValueError("Backup and restore require a PostgreSQL database URL.")
    return parsed


def _connection_arguments(database: URL) -> list[str]:
    arguments = [f"--dbname={database.database}"]
    if database.host:
        arguments.append(f"--host={database.host}")
    if database.port:
        arguments.append(f"--port={database.port}")
    if database.username:
        arguments.append(f"--username={database.username}")
    return arguments


def _required_executable(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(
            f"{name} is required. Install the PostgreSQL client tools first."
        )
    return executable


def _run(command: list[str], database: URL) -> None:
    environment = os.environ.copy()
    if database.password is not None:
        environment["PGPASSWORD"] = database.password
    sslmode = database.query.get("sslmode")
    if isinstance(sslmode, str):
        environment["PGSSLMODE"] = sslmode
    try:
        subprocess.run(
            command,
            check=True,
            env=environment,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        message = error.stderr.strip() or "PostgreSQL command failed."
        raise RuntimeError(message) from error


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Back up or restore the BibMgR PostgreSQL database."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    backup_parser = commands.add_parser("backup")
    backup_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("backups"),
    )
    restore_parser = commands.add_parser("restore")
    restore_parser.add_argument("--input", type=Path, required=True)
    restore_parser.add_argument("--confirm-database", required=True)
    arguments = parser.parse_args()

    if arguments.command == "backup":
        destination = backup_database(
            url=database_url(),
            output_directory=arguments.output_dir,
        )
        print(destination)
        return

    restore_database(
        url=database_url(),
        input_path=arguments.input,
        confirmed_database=arguments.confirm_database,
    )
    print(f"Restored {arguments.input}.")


if __name__ == "__main__":  # pragma: no cover
    main()
