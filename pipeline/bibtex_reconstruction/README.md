**BibTeX Reconstruction**

簡単な説明: 画像やPDFから抽出した参照文字列を基に外部APIと照合し、整形済みのBibTeXを再構築する小さなパイプラインです。FastAPIで公開されたエンドポイントから利用できます。

**Requirements**
- **Python**: 3.12以上（`.python-version`に3.12を指定）
- 依存関係は `pyproject.toml`  `uv.lock` に記載されています。

**Project Structure**
- `main.py`: FastAPI アプリケーション (`POST /reconstruct`)。
- `config.yml`: パイプライン設定（類似度閾値、APIエンドポイント、会議名辞書など）。
- `api_clients/`: Crossref, CiNii, Semantic Scholar, J-Stage, arXiv, およびローカルDBクライアント。
- `core/`: 設定読み込み・ユーティリティ関数。
- `models/`: `InputData` / `OutputData` のPydanticモデル。
- `services/`: 検索の Orchestrator (`orchestrator.py`) と BibTeX 整形ロジック (`formatter.py`)。
- `test_data/`: サンプルレスポンスやテスト用JSON。

**セットアップ（ローカル）**
```bash
uv sync
```

`.env` にAPIキーやメールアドレスなどの環境変数を設定してください（例: `CINII_APPID`, `SEMANTIC_SCHOLAR_API_KEY`, `CROSSREF_MAILTO`）。

**起動方法**

開発モードで FastAPI サーバを起動するには:
```bash
uv run uvicorn main:app --reload 
```

起動後、OpenAPIドキュメントは `http://localhost:8000/docs` で確認できます。

**API (POST /reconstruct)**
- 入力モデルは `models.InputData` を参照します。最小例:

```json
{
  "source_pdf": "title.pdf",
  "ref_id": "ref-number",
  "raw_reference_text": "name. title. xx.",
  "parsed_data": {
    "title": "title",
    "authors": ["name"],
    "year": 1111,
    "venue": "venue"
  },
  "citation_contexts": ["According to name..."]
}
```

- 戻り値は `models.OutputData` を返します。`status` は `success` / `needs_review` / `not_found` のいずれかになります。


**設定**
- しきい値や外部APIのエンドポイントは `config.yml` で管理されています。
- APIキー等は `.env` で指定します。`core.config` がこれらを読み込みます。

**テストデータ**
- `test_data/` にサンプルJSONが入っています。動作確認や単体デバッグに利用してください。

**開発メモ**
- 検索の流れ: `services.orchestrator` がローカルDBをまず確認し、見つからなければ外部クライアント群に順次問い合わせ、最も高い類似度の結果を `needs_review` として返します。
- 整形ルール: `services.formatter.apply_lab_rules` がBibTeXのフィールド抽出・補完・キー生成を行います。

**BibMgRローカルDB連携**

`config.yml`の`api.localdb.enabled`を`true`にすると、外部APIより先にBibMgRの公開検索APIを参照します。開発時のendpointは`http://127.0.0.1:8000/references/page`、本番は`https://HOST/api/references/page`を指定します。loopback以外の平文HTTPは拒否され、検索にlogin credentialは使用しません。

このパイプラインはBibMgRアプリとは独立した初期化処理です。BibMgRのフロントエンドは再構築JSONの読み込みを行わず、バックエンドもパイプライン専用の登録APIを公開しません。再構築結果の確認と永続化はパイプライン側の運用として管理します。
