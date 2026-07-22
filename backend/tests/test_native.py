import json
from types import SimpleNamespace

import pytest

from bibmgr_backend.native import NativeCallError, NativeEngine, _to_jsonable


def test_native_json_string_is_converted_to_an_object() -> None:
    native = SimpleNamespace(
        analyze=lambda source, **kwargs: json.dumps(
            {"schema_version": "1", "source": source, **kwargs}
        )
    )
    engine = NativeEngine(native)

    assert engine.analyze("input", "acl", "strict") == {
        "schema_version": "1",
        "source": "input",
        "profile": "acl",
        "mode": "strict",
    }


def test_native_object_to_dict_is_supported() -> None:
    value = SimpleNamespace(to_dict=lambda: {"schema_version": "1", "items": []})

    assert _to_jsonable(value) == {"schema_version": "1", "items": []}


def test_export_profiles_calls_the_native_catalog_without_arguments() -> None:
    calls: list[tuple[object, ...]] = []

    def export_profiles(*args: object) -> object:
        calls.append(args)
        return SimpleNamespace(
            to_dict=lambda: {
                "schema_version": "1",
                "profiles": [{"id": "modern"}],
            }
        )

    engine = NativeEngine(SimpleNamespace(export_profiles=export_profiles))

    assert engine.export_profiles() == {
        "schema_version": "1",
        "profiles": [{"id": "modern"}],
    }
    assert calls == [()]


def test_native_exception_is_mapped_without_document_rule_logic() -> None:
    class EditConflictError(Exception):
        pass

    def fail(*args: object, **kwargs: object) -> None:
        raise EditConflictError("stale source")

    engine = NativeEngine(SimpleNamespace(apply_fixes=fail))

    with pytest.raises(NativeCallError) as captured:
        engine.apply_fixes("source", "sha256:" + "0" * 64, ["fix"], "laboratory")

    assert captured.value.code == "edit_conflict"
    assert captured.value.status_code == 409
