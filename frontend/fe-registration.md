# Frontend Registration UI Definitions

## Scope

文献登録UIは、次の2つのBibTeX入力方法を提供する。

- BibTeX entryをエディタへ直接入力する。
- `.bib` ファイルをブラウザ内で読み込み、内容を確認・編集して登録する。

PDFアップロードとPDFからの候補抽出は対象外とする。登録後にバックエンドから文献データが返った場合は、画面上の文献一覧へ追加し、その文献を選択状態にする。

## Frontend Placement

文献一覧の「Add reference」ボタンからモーダルを開く。モーダル内の `Manual entry` と `BibTeX file` はタブとして切り替える。

`.bib` ファイルはバックエンドへファイルとしてアップロードしない。ブラウザの `File.text()` で読み込み、既存のBibTeX文字列登録APIへ渡す。

ファイル入力は次の制約を持つ。

- 拡張子は `.bib`（大文字・小文字を区別しない）
- 最大サイズは2 MB
- 1ファイルに1つ以上の文献entry
- UTF-8 BOMは読み込み時に除去

複数entryを含むファイルは全文を保持したまま一度に登録処理へ渡す。entryの分割や部分失敗時の扱いはバックエンド実装時に定義する。

## Environment Variables

- `VITE_API_BASE_URL`
  - フロントエンドが呼び出すAPIベースURL。
  - 未設定時は `/api` を使用する。
  - 開発時はVite proxyで `/api` を `http://localhost:8000` へ転送する。
- `VITE_BIBMGR_API_KEY`
  - 設定されている場合、APIリクエストに `X-API-Key` ヘッダとして付与する。
  - 未設定時はヘッダを付与しない。

## API Contract

### DB Registration

`POST /references`

開発時のフロントエンドからは `/api/references` を呼ぶ。

手動入力とファイル入力は、どちらも読み込んだBibTeX文字列を送信する。ファイル入力では複数entryを含む全文を `bibtex` に格納する。

Request:

```json
{
  "bibtex": "@article{...}",
  "source": "manual"
}
```

ファイル入力では `source` を `file` とする。

```json
{
  "bibtex": "@article{...}\n\n@book{...}",
  "source": "file"
}
```

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

バックエンドの文献登録APIはまだリポジトリ内に実装されていないため、次の定義は今後必要となる。

- DB登録APIの正式なエンドポイント名と認証方式
- 重複判定でBibTeX key、DOI、titleのどれを優先するか
- 登録後レスポンスに含める正式な文献スキーマ
- 複数BibTeX entryの一括登録と部分失敗時のレスポンス形式
