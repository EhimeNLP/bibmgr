from pathlib import Path
import shlex
import sys

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from bibmgr_backend.db_models import Base, ReferenceRecord, ReferenceSearchTranslation
from bibmgr_backend.search import ReferenceSearch, mark_search_change
from bibmgr_backend.translation import TranslationError, TranslationModel, translator_from_environment
from bibmgr_backend.translation_jobs import TranslationWorker


class TestTranslator:
    __test__ = False

    def __init__(self, revision, results):
        self.identity = TranslationModel("test", "example", revision)
        self.results = results

    def translate(self, text, source, target):
        result = self.results[text, source, target]
        if isinstance(result, Exception):
            raise result
        return result() if callable(result) else result

    def close(self):
        pass


def test_persist_backfill_both_directions_and_model_migration(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'translation.sqlite'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions.begin() as session:
        english = _reference("Landmark Detection", "en", "Pose estimation")
        japanese = _reference("文書質問応答", "ja")
        session.add_all([english, japanese])
        session.flush()
        en_id, ja_id = english.id, japanese.id
        mark_search_change(session, en_id)
        mark_search_change(session, ja_id)

    search = ReferenceSearch(include_translations=True)

    def matches(query, **filters):
        with sessions() as session:
            return search.search(session, query=query, limit=10, **filters)[0]

    assert matches("姿勢推定") == []
    v1 = TestTranslator("v1", {
        ("Landmark Detection", "en", "ja"): "特徴点検出",
        ("Pose estimation", "en", "ja"): "姿勢推定",
        ("文書質問応答", "ja", "en"): "Document Question Answering",
    })
    worker = TranslationWorker(sessions, v1)
    assert worker.process_batch()[0] == 2
    assert worker.process_batch()[0] == 0
    assert matches("姿勢推定") == [en_id]
    assert matches("document question answering") == [ja_id]
    assert matches("document question answering", search_mode="original") == []

    v2 = TestTranslator("v2", {
        ("Landmark Detection", "en", "ja"): TranslationError("temporary failure"),
        ("Pose estimation", "en", "ja"): "姿勢推定",
        ("文書質問応答", "ja", "en"): "Document QA",
    })
    second_worker = TranslationWorker(sessions, v2)
    assert second_worker.process_batch()[0] == 2
    with sessions() as session:
        assert session.get(ReferenceSearchTranslation, en_id).model_revision == "v1"
        assert session.get(ReferenceSearchTranslation, ja_id).model_revision == "v2"
    assert matches("特徴点検出") == [en_id]

    def edit_during_translation():
        with sessions.begin() as session:
            record = session.get(ReferenceRecord, en_id)
            record.title = "Language Models"
            record.source_revision = "sha256:" + "b" * 64
            mark_search_change(session, en_id)
        return "特徴点の検出"

    v2.results["Landmark Detection", "en", "ja"] = edit_during_translation
    assert second_worker.process_batch()[0] == 1
    assert matches("特徴点検出") == []
    assert matches("language models") == [en_id]
    v2.results["Language Models", "en", "ja"] = "言語モデル"
    assert second_worker.process_batch()[0] == 1
    assert matches("言語モデル") == [en_id]
    with sessions.begin() as session:
        session.delete(session.get(ReferenceRecord, en_id))
        mark_search_change(session, en_id)
    with sessions() as session:
        assert session.get(ReferenceSearchTranslation, en_id) is None
    assert matches("言語モデル") == []


def _reference(title, language, keywords=None):
    fields = [{"name": "langid", "value": {"resolved": language}}]
    if keywords:
        fields.append({"name": "keywords", "value": {"resolved": keywords}})
    return ReferenceRecord(
        title=title, citation_key=f"example-2025-{language}", entry_type="article",
        work_type="journal_article", canonical_bibtex=f"@article{{example,title={{{title}}}}}",
        source_revision="sha256:" + "a" * 64, registration_source="manual",
        semantic_data={"extra_fields": fields},
    )


def test_operators_can_choose_an_arbitrary_command_or_python_provider(monkeypatch):
    prefix = "BIBMGR_SEARCH_TRANSLATION_"
    monkeypatch.delenv(prefix + "PROVIDER", raising=False)
    assert translator_from_environment() is None
    monkeypatch.setenv(prefix + "MODEL", "an-arbitrary-model")
    monkeypatch.setenv(prefix + "REVISION", "v7")
    monkeypatch.setenv(prefix + "PROVIDER", "command")
    monkeypatch.setenv(prefix + "COMMAND", shlex.join([
        sys.executable, "-c",
        'import sys,json; x=json.load(sys.stdin); assert x["source_lang"]=="ja" and x["target_lang"]=="en"; '
        'print(json.dumps({"translation": "Language Models"}))',
    ]))
    command = translator_from_environment()
    assert command.translate("言語モデル", "ja", "en") == "Language Models"
    command.close()

    monkeypatch.setenv(prefix + "PROVIDER", f"{__name__}:make_test_provider")
    adapter = translator_from_environment()
    assert adapter.identity.model == "an-arbitrary-model"
    assert adapter.translate("言語モデル", "ja", "en") == "Language Models"


def make_test_provider(identity):
    provider = TestTranslator(identity.revision, {("言語モデル", "ja", "en"): "Language Models"})
    provider.identity = identity
    return provider
