"""The only backend boundary to the Rust implementation.

There is deliberately no BibTeX interpretation here. This module converts
owned PyO3 DTOs to JSON-compatible values and maps native exception classes to
HTTP-level error metadata.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from importlib import import_module
import json
from types import ModuleType
from typing import Any


class NativeCallError(RuntimeError):
    """Stable adapter error produced from a native exception."""

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


_ERROR_MAP: dict[str, tuple[str, int]] = {
    "ParseError": ("parse_error", 422),
    "ValidationError": ("validation_error", 422),
    "EditConflictError": ("edit_conflict", 409),
    "ExportError": ("export_error", 422),
    "ConfigurationError": ("configuration_error", 400),
}


class NativeEngine:
    """Lazy, injectable facade over :mod:`bibmgr_native`."""

    def __init__(self, native_module: ModuleType | Any | None = None) -> None:
        self._native_module = native_module

    @property
    def native(self) -> Any:
        if self._native_module is None:
            try:
                self._native_module = import_module("bibmgr_native")
            except ImportError as error:
                raise NativeCallError(
                    "native_extension_unavailable",
                    "bibmgr_native is not installed; build it with maturin",
                    503,
                ) from error
        return self._native_module

    def analyze(self, source: str, profile: str, mode: str) -> dict[str, Any]:
        return self._call("analyze", source, profile=profile, mode=mode)

    def apply_fixes(
        self, source: str, source_revision: str, fix_ids: list[str], profile: str
    ) -> dict[str, Any]:
        return self._call(
            "apply_fixes",
            source,
            fix_ids=fix_ids,
            profile=profile,
            source_revision=source_revision,
        )

    def validate_for_registration(
        self, source: str, policy: str
    ) -> dict[str, Any]:
        return self._call(
            "validate_for_registration", source, policy=policy
        )

    def export_profiles(self) -> dict[str, Any]:
        return self._call("export_profiles")

    def export_source(self, source: str, profile: str) -> dict[str, Any]:
        return self._call("export_source", source, profile=profile)

    def _call(self, function_name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            function = getattr(self.native, function_name)
            result = function(*args, **kwargs)
            dto = _to_jsonable(result, decode_transport_json=True)
        except NativeCallError:
            raise
        except Exception as error:  # PyO3 exception classes are runtime-defined.
            code, status_code = _ERROR_MAP.get(
                type(error).__name__, ("native_error", 500)
            )
            raise NativeCallError(code, str(error), status_code) from error

        if not isinstance(dto, dict):
            raise NativeCallError(
                "invalid_native_response",
                f"bibmgr_native.{function_name} returned a non-object DTO",
                500,
            )
        return dto


def _to_jsonable(value: Any, *, decode_transport_json: bool = False) -> Any:
    """Convert an owned native DTO without changing its field semantics."""

    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and decode_transport_json:
            stripped = value.lstrip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    return _to_jsonable(json.loads(value))
                except json.JSONDecodeError:
                    pass
        return value
    if isinstance(value, Enum):
        return _to_jsonable(value.value)
    if is_dataclass(value) and not isinstance(value, type):
        return _to_jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_to_jsonable(item) for item in value]

    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _to_jsonable(to_dict())
    to_json = getattr(value, "to_json", None)
    if callable(to_json):
        return _to_jsonable(to_json(), decode_transport_json=True)

    public_values = {
        name: _to_jsonable(item)
        for name, item in vars(value).items()
        if not name.startswith("_")
    } if hasattr(value, "__dict__") else {}
    if public_values:
        return public_values

    raise TypeError(f"unsupported native DTO type: {type(value).__name__}")
