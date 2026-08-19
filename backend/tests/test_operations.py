from datetime import datetime, timezone
from pathlib import Path
import subprocess

import pytest

from bibmgr_backend import operations


DATABASE_URL = "postgresql+psycopg://bibmgr:secret@db:5433/bibmgr"


def test_backup_uses_custom_format_without_exposing_password(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    monkeypatch.setattr(
        operations.shutil, "which", lambda name: f"/usr/bin/{name}"
    )

    def run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        calls.append((command, environment))
        output = next(
            item.removeprefix("--file=")
            for item in command
            if item.startswith("--file=")
        )
        Path(output).write_bytes(b"backup")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(operations.subprocess, "run", run)

    destination = operations.backup_database(
        url=DATABASE_URL,
        output_directory=tmp_path,
        now=datetime(2026, 7, 28, 1, 2, 3, tzinfo=timezone.utc),
    )

    assert destination.name == "bibmgr-20260728T010203Z.dump"
    assert destination.read_bytes() == b"backup"
    command, environment = calls[0]
    assert "--format=custom" in command
    assert "--host=db" in command
    assert "--port=5433" in command
    assert "--username=bibmgr" in command
    assert all("secret" not in argument for argument in command)
    assert environment["PGPASSWORD"] == "secret"
    assert destination.stat().st_mode & 0o777 == 0o600


def test_restore_requires_exact_database_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"backup")
    monkeypatch.setattr(
        operations.shutil, "which", lambda name: f"/usr/bin/{name}"
    )

    with pytest.raises(ValueError, match="exactly match"):
        operations.restore_database(
            url=DATABASE_URL,
            input_path=backup,
            confirmed_database="other",
        )


def test_restore_cleans_target_and_stops_on_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    backup = tmp_path / "backup.dump"
    backup.write_bytes(b"backup")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        operations.shutil, "which", lambda name: f"/usr/bin/{name}"
    )
    monkeypatch.setattr(
        operations.subprocess,
        "run",
        lambda command, **_kwargs: calls.append(command),
    )

    operations.restore_database(
        url=DATABASE_URL,
        input_path=backup,
        confirmed_database="bibmgr",
    )

    assert "--clean" in calls[0]
    assert "--if-exists" in calls[0]
    assert "--exit-on-error" in calls[0]
