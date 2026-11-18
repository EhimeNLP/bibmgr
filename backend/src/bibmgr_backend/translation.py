"""Provider contract and configuration for optional search translation."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
import json
import os
import shlex
import shutil
import subprocess
from threading import Lock
from typing import Protocol


@dataclass(frozen=True)
class TranslationModel:
    provider: str
    model: str
    revision: str


class TranslationError(RuntimeError):
    pass


class Translator(Protocol):
    identity: TranslationModel

    def translate(self, text: str, source: str, target: str) -> str: ...

    def close(self) -> None: ...


class CommandTranslator:
    """Run an operator-provided executable using the JSON translation contract."""

    def __init__(self, identity: TranslationModel, command: list[str], timeout: int) -> None:
        self.identity = identity
        self._command = command
        self._timeout = timeout
        self._lock = Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._closed = False

    def translate(self, text: str, source: str, target: str) -> str:
        payload = json.dumps({"text": text, "source_lang": source, "target_lang": target}).encode()
        try:
            with self._lock:
                if self._closed:
                    raise TranslationError("Translation worker is stopping")
                process = self._process = subprocess.Popen(
                    self._command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
            with process:
                try:
                    output, _ = process.communicate(payload, timeout=self._timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    raise
            if process.returncode:
                raise TranslationError("Translation command exited unsuccessfully")
            return translation_text(json.loads(output)["translation"])
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as error:
            raise TranslationError("Translation command failed or returned invalid JSON") from error
        finally:
            with self._lock:
                self._process = None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._process is not None and self._process.poll() is None:
                self._process.kill()


def translation_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4096 or "\0" in value:
        raise TranslationError("Invalid translation text")
    return value.strip()


def _required(suffix: str) -> str:
    name = "BIBMGR_SEARCH_TRANSLATION_" + suffix
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Set {name} to enable search translation")
    return value


def translator_from_environment() -> Translator | None:
    provider = os.environ.get("BIBMGR_SEARCH_TRANSLATION_PROVIDER", "").strip()
    if not provider:
        return None
    identity = TranslationModel(provider, _required("MODEL"), _required("REVISION"))
    if max(len(identity.provider), len(identity.model), len(identity.revision)) > 255:
        raise RuntimeError("Translation provider, model and revision must be at most 255 characters")
    if provider == "command":
        command = shlex.split(_required("COMMAND"))
        if not command or not shutil.which(command[0]):
            raise RuntimeError("Translation command executable was not found")
        key = "BIBMGR_SEARCH_TRANSLATION_TIMEOUT_SECONDS"
        try:
            timeout = int(os.environ.get(key, "30"))
        except ValueError as error:
            raise RuntimeError(f"{key} must be an integer between 1 and 300") from error
        if not 1 <= timeout <= 300:
            raise RuntimeError(f"{key} must be an integer between 1 and 300")
        return CommandTranslator(identity, command, timeout)
    module, separator, name = provider.partition(":")
    if not separator or not name.isidentifier() or not all(part.isidentifier() for part in module.split(".")):
        raise RuntimeError("BIBMGR_SEARCH_TRANSLATION_PROVIDER must be command or module:factory")
    factory = getattr(import_module(module), name)
    translator = factory(identity)
    if translator.identity != identity:
        raise RuntimeError("Translation provider must use the configured model identity")
    return translator
