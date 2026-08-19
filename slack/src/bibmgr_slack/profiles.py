"""Built-in and deployment-bundled Slack export profiles."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Protocol
import tomllib


class ProfileConfigurationError(ValueError):
    """Raised when the deployed Slack profile catalog is invalid."""


class NativeProfileEngine(Protocol):
    def export_profiles(self) -> Any: ...

    def validate_export_profile(self, profile_json: str) -> str: ...


@dataclass(frozen=True)
class ProfileSpec:
    id: str
    display_name: str
    description: str
    validation_profile: str
    profile_json: str | None = None

    def option(self, language: str) -> dict[str, Any]:
        label = self.display_name if language == "en" else self.id
        if len(label) > 75:
            label = f"{label[:72]}..."
        return {
            "text": {"type": "plain_text", "text": label},
            "value": self.id,
        }


@dataclass(frozen=True)
class ProfileCatalog:
    profiles: tuple[ProfileSpec, ...]

    def by_id(self, profile_id: str) -> ProfileSpec | None:
        return next(
            (profile for profile in self.profiles if profile.id == profile_id),
            None,
        )


def load_profile_catalog(
    engine: NativeProfileEngine, profile_directory: Path
) -> ProfileCatalog:
    catalog = engine.export_profiles().to_dict()
    profiles = [_profile_from_mapping(item) for item in catalog["profiles"]]
    if any(len(profile.id) > 75 for profile in profiles):
        raise ProfileConfigurationError(
            "Slack export profile IDs must not exceed 75 characters"
        )
    known = {profile.id for profile in profiles}

    if not profile_directory.is_dir():
        raise ProfileConfigurationError(
            f"Slack profile directory does not exist: {profile_directory}"
        )
    for path in sorted(profile_directory.glob("*.toml")):
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
        try:
            validated = json.loads(
                engine.validate_export_profile(
                    json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
                )
            )["profile"]
        except Exception as error:
            raise ProfileConfigurationError(
                f"invalid Slack export profile {path.name}: {error}"
            ) from error
        profile_id = str(validated["profile"])
        if len(profile_id) > 75:
            raise ProfileConfigurationError(
                f"Slack export profile id exceeds 75 characters: {profile_id}"
            )
        if profile_id in known:
            raise ProfileConfigurationError(
                f"duplicate Slack export profile id: {profile_id}"
            )
        known.add(profile_id)
        profiles.append(
            _profile_from_mapping(
                validated,
                profile_json=json.dumps(
                    validated, ensure_ascii=False, separators=(",", ":")
                ),
            )
        )
    if len(profiles) > 100:
        raise ProfileConfigurationError(
            "Slack static select menus support at most 100 export profiles"
        )
    return ProfileCatalog(tuple(profiles))


def _profile_from_mapping(
    value: dict[str, Any], *, profile_json: str | None = None
) -> ProfileSpec:
    return ProfileSpec(
        id=str(value.get("id", value.get("profile", ""))),
        display_name=str(value["display_name"]),
        description=str(value["description"]),
        validation_profile=str(value["validation_profile"]),
        profile_json=profile_json,
    )
