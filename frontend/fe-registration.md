# Frontend Registration UI Definitions

## Branch

- Working branch: `feat/frontend-registration-ui`
- Base branch: `feat/vue-frontend-base`
- Pull request target: `feat/vue-frontend-base`

## Scope

このブランチでは、既存の検索UIと文献一覧・詳細表示の構造を大きく変更せず、登録用UIを追加する。

対象機能は次の3つとする。

- PDFをフロントエンドからバックエンドへ渡す。
- PDF処理で得られたBibTeX候補を確認し、`needs_review` 相当の候補を画面上で修正できる。
- BibTeX文字列をDBへ直接登録できる。

## Frontend Placement

登録UIは検索欄の下、文献一覧と詳細表示の上に配置する。

既存の検索欄、文献一覧、文献詳細のコンポーネント構成は維持する。登録後にバックエンドから文献データが返る場合は、画面上の文献一覧へ追加し、その文献を選択状態にする。

## Environment Variables

- `VITE_API_BASE_URL`
  - フロントエンドが呼び出すAPIベースURL。
  - 未設定時は `/api` を使用する。
  - 開発時はVite proxyで `/api` を `http://localhost:8000` へ転送する。
- `VITE_BIBMGR_API_KEY`
  - 設定されている場合、APIリクエストに `X-API-Key` ヘッダとして付与する。
  - 未設定時はヘッダを付与しない。

## API Contract

バックエンドのPDF登録・DB登録APIはまだリポジトリ内で確定していないため、フロントエンドでは以下の契約を前提にする。

### PDF Processing

`POST /registrations/pdf`

開発時のフロントエンドからは `/api/registrations/pdf` を呼ぶ。

Request:

- `multipart/form-data`
- field: `pdf`
- value: PDF file

Response:

```json
{
  "upload_id": "upload-123",
  "source_file_name": "paper.pdf",
  "references": [
    {
      "id": "ref-1",
      "title": "Paper title",
      "authors": ["Author A", "Author B"],
      "year": 2024,
      "venue": "Venue",
      "doi": "10.0000/example",
      "bibtex": "@article{...}",
      "status": "needs_review",
      "confidence_score": 0.82,
      "source_api": "Crossref",
      "raw_reference_text": "..."
    }
  ]
}
```

`status` は次のいずれかとする。

- `success`
- `needs_review`
- `not_found`
- `api_error`

フロントエンドは `references` の各要素を編集可能なBibTeX候補として表示する。既存のBibTeX復元API `POST /reconstruct` の `processed_references` 形式が返る場合も、候補を画面用の形式へ変換する。

### DB Registration

`POST /references`

開発時のフロントエンドからは `/api/references` を呼ぶ。

Request:

```json
{
  "bibtex": "@article{...}",
  "source": "pdf",
  "uploadId": "upload-123",
  "reviewItemId": "ref-1",
  "metadata": {
    "title": "Paper title",
    "authors": ["Author A", "Author B"],
    "year": 2024,
    "venue": "Venue",
    "doi": "10.0000/example"
  }
}
```

直接BibTeX登録の場合は `source` を `manual` とし、`uploadId` と `reviewItemId` は送らない。

Response:

```json
{
  "reference": {
    "id": "db-reference-id",
    "title": "Paper title",
    "authors": ["Author A", "Author B"],
    "year": 2024,
    "venue": "Venue",
    "doi": "10.0000/example",
    "url": "https://example.com",
    "bibtexKey": "author-2024-venue-key",
    "bibtex": "@article{...}"
  }
}
```

## Required Backend Definitions

追加で決める必要がある定義は以下。

- PDF登録APIの正式なエンドポイント名。
- DB登録APIの正式なエンドポイント名。
- PDF処理を同期レスポンスにするか、ジョブIDを返す非同期処理にするか。
- PDFの最大サイズ、対応MIME type、エラー時のレスポンス形式。
- `needs_review` の判定基準と、`success` 候補も編集可能にするかどうか。
- DB登録時の重複判定ルール。BibTeX key、DOI、titleのどれを優先するか。
- 登録後レスポンスに含める正式な文献スキーマ。
- 認証方式。現状の `X-API-Key` を登録APIにも適用するか。
- 複数BibTeX候補を一括登録するAPIが必要か。
