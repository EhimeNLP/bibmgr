# Frontend Registration UI Definitions

## Scope

文献登録UIは、次の2つの入力方法を提供する。

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
    "bibtex": "@article{...}",
    "sourceRevision": "sha256:..."
  },
  "references": []
}
```

`reference`は既存UIとの互換性のための先頭entryであり, `references`には同じトランザクションで登録された全entryを格納する. 単一entryの場合も`references`は1件を含む.

## Backend Decisions

- 永続化APIは`/references`に統一する.
- 登録時のポリシーはサーバー側の`BIBMGR_REGISTRATION_POLICY`で固定し, クライアントから変更できない.
- DOIとarXiv IDはDBの一意インデックスで強い重複として扱う. BibTeX keyとtitleはグローバルな一意条件にしない.
- 複数BibTeX entryは1トランザクションで登録する. 1件でも検証または一意制約に失敗した場合は全件をロールバックする.
- 既定の`archive`登録ポリシーはstrict parse failureのみを拒否し, 研究室ルール, field不足, 未解決semantic valueは登録を妨げない.
- フロントエンドの検査とfixは任意の補助機能とし, 登録ボタンは現在の入力を1回で永続化APIへ送る. 保存前のcanonical previewや再確認は行わない.
- 登録・ファイル登録・編集画面には保存処理から独立したoutput previewを1つ表示する. 既定は`laboratory`で, profile選択時は同じpreviewをexport APIで再生成する. 選択profileと生成結果は保存payloadへ反映しない.
- DBの現在値は入力BibTeXをprofileで書き換えず保存し, semantic snapshotを検索用projectionとして併記する. revision履歴も正確な保存sourceとsemantic snapshotを保持する.
- 編集は`PUT /references/{id}`で行い, 保存済み`sourceRevision`を`source_revision`として要求する.
- 削除は`DELETE /references/{id}`で行い, 関連する著者, 識別子, URL, 引用文脈も削除する.
- 削除は読み込み時の`sourceRevision`をquoted `If-Match` headerとして送り, staleな削除をHTTP 409で拒否する.
- 編集・削除は完全な関係データを連番revisionとして保持する. `GET /reference-history`は削除済み文献も返し, `GET /references/{id}/history`は保存BibTeXを返し, `POST /references/{id}/revert`は選択した過去状態を新しいrevisionとして復元する.
- 検索, 詳細取得, BibTeX検査・出力は未ログインでも利用できる.
- 登録, 編集, 削除はメール認証済みセッションを要求する. フロントエンドはHttpOnly Cookieを`credentials: "include"`で送信し, セッションAPIから取得したCSRFトークンを`X-CSRF-Token`へ設定する.
