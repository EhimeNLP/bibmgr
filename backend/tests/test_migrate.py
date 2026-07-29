import sys
from pathlib import Path

import pytest

from bibmgr_backend.migrate import (
    ResetRefusedError,
    local_postgresql_target,
    main,
    migration_config,
    reset_database,
)


def test_migrations_are_available_from_the_installed_package() -> None:
    script_location = migration_config().get_main_option("script_location")
    migrations = Path(script_location)

    assert migrations.joinpath("env.py").is_file()
    assert migrations.joinpath(
        "versions", "0001_reference_library.py"
    ).is_file()
    assert migrations.joinpath(
        "versions", "0002_email_authentication.py"
    ).is_file()
    assert migrations.joinpath(
        "versions", "0003_revertible_history.py"
    ).is_file()
    assert migrations.joinpath(
        "versions", "0004_context_history.py"
    ).is_file()
    assert migrations.joinpath(
        "versions", "0005_application_configuration.py"
    ).is_file()
    assert migrations.joinpath(
        "versions", "0006_configuration_deletions.py"
    ).is_file()
    assert migrations.joinpath(
        "versions", "0007_configuration_audit_actions.py"
    ).is_file()


def test_reset_target_must_be_local_postgresql() -> None:
    target = local_postgresql_target(
        "postgresql+psycopg://bibmgr:secret@127.0.0.1:5432/bibmgr"
    )

    assert target.database == "bibmgr"
    with pytest.raises(ResetRefusedError, match="localhost"):
        local_postgresql_target(
            "postgresql+psycopg://bibmgr:secret@db.example/bibmgr"
        )
    with pytest.raises(ResetRefusedError, match="PostgreSQL"):
        local_postgresql_target("sqlite:///bibmgr.db")


def test_reset_requires_database_name_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "bibmgr_backend.migrate.database_url",
        lambda: "postgresql+psycopg://bibmgr:secret@localhost/bibmgr",
    )
    monkeypatch.setattr(
        "bibmgr_backend.migrate.command.downgrade",
        lambda _config, revision: calls.append(("downgrade", revision)),
    )
    monkeypatch.setattr(
        "bibmgr_backend.migrate.command.upgrade",
        lambda _config, revision: calls.append(("upgrade", revision)),
    )

    cancelled = reset_database(
        migration_config(),
        assume_yes=False,
        prompt=lambda _message: "wrong-name",
    )
    completed = reset_database(
        migration_config(),
        assume_yes=False,
        prompt=lambda _message: "bibmgr",
    )

    assert cancelled is False
    assert completed is True
    assert calls == [("downgrade", "base"), ("upgrade", "head")]


def test_noninteractive_reset_requires_development_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bibmgr_backend.migrate.database_url",
        lambda: "postgresql+psycopg://bibmgr:secret@localhost/bibmgr",
    )
    monkeypatch.delenv("BIBMGR_ENV", raising=False)

    with pytest.raises(ResetRefusedError, match="BIBMGR_ENV"):
        reset_database(migration_config(), assume_yes=True)


def test_yes_option_is_rejected_for_non_reset_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["bibmgr-db", "upgrade", "--yes"])

    with pytest.raises(SystemExit, match="2"):
        main()
