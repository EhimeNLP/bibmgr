from __future__ import annotations

import json
from pathlib import Path

import pytest

from bibmgr_slack.profiles import ProfileConfigurationError, load_profile_catalog


class Dto:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value

    def to_dict(self) -> dict[str, object]:
        return self.value


class Engine:
    def export_profiles(self) -> Dto:
        return Dto(
            {
                "profiles": [
                    {
                        "id": "modern",
                        "display_name": "Modern",
                        "description": "Built in",
                        "validation_profile": "modern",
                    }
                ]
            }
        )

    def validate_export_profile(self, profile_json: str) -> str:
        return json.dumps({"schema_version": "1", "profile": json.loads(profile_json)})


def write_profile(path: Path, profile_id: str) -> None:
    path.write_text(
        "\n".join(
            (
                'schema_version = "1"',
                f'profile = "{profile_id}"',
                'display_name = "Custom"',
                'description = "Custom profile"',
                'validation_profile = "modern"',
            )
        ),
        encoding="utf-8",
    )


def test_merges_deployment_profiles_after_builtins(tmp_path: Path) -> None:
    write_profile(tmp_path / "custom.toml", "custom")

    catalog = load_profile_catalog(Engine(), tmp_path)

    assert [profile.id for profile in catalog.profiles] == ["modern", "custom"]
    assert catalog.by_id("custom").profile_json is not None  # type: ignore[union-attr]
    assert catalog.by_id("custom").option("ja")["text"]["text"] == "custom"  # type: ignore[union-attr]


def test_rejects_duplicate_builtin_id(tmp_path: Path) -> None:
    write_profile(tmp_path / "duplicate.toml", "modern")

    with pytest.raises(ProfileConfigurationError):
        load_profile_catalog(Engine(), tmp_path)
