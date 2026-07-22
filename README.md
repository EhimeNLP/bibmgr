# bibmgr

## 環境構築

まず, 依存関係をインストールしてください.

```bash
uv sync
uv run poe setup
```

利用可能なタスクは次のコマンドで確認できます.

```bash
uv run poe --help
```

## CLIのインストール (Optional)

BibTeX検証をCLIツールとして使用したい場合は, 以下でインストールしてください. CLIの実行ファイル名は `bibmgr` です.

```bash
cargo install --locked --path crates/bibmgr-cli
bibmgr --version
```

更新時はチェックアウトを更新してから再インストールします.

```bash
cargo install --locked --force --path crates/bibmgr-cli
```

インストールせずにリリース用バイナリを生成する場合はPoe taskを使用します.

```bash
uv run --frozen poe build-cli
./target/release/bibmgr --version
```

## CLIの利用

基本的なコマンドは次のとおりです. 詳細なオプションは `bibmgr COMMAND --help`, 終了コードやJSON出力仕様は[`docs/cli.md`](docs/cli.md)で確認できます.

```bash
# 検査
bibmgr lint references.bib --profile laboratory

# CI向けJSON出力
bibmgr lint references.bib --profile laboratory --format json

# source-preservingな安全な修正をpreview
bibmgr fix references.bib --safe --dry-run

# laboratory profile向けに最適化して別ファイルへexport
bibmgr export references.bib --profile laboratory --output references.exported.bib

# export結果をJSON DTOとして取得
bibmgr export references.bib --profile classical-bst --format json

# semantic ASTを確認
bibmgr inspect references.bib --ast
```

## 開発環境

バックエンドとフロントエンドの開発サーバを同時に起動します.

```bash
uv run poe dev
```

- Frontend: `http://127.0.0.1:5173/`
- Backend: `http://127.0.0.1:8000/`
- Health check: `http://127.0.0.1:8000/healthz`
- API documentation: `http://127.0.0.1:8000/docs`

個別に起動する場合は別々のターミナルで実行します.

```bash
uv run poe dev-backend
uv run poe dev-frontend
```

待ち受けアドレスとポートは環境変数で変更できます.

```bash
HOST=127.0.0.1 PORT=8000 \
FRONTEND_HOST=127.0.0.1 FRONTEND_PORT=5173 \
uv run poe dev
```

テスト一式と, format・lint・typecheck・lockfile・schema・Markdown・fuzz/benchmark buildを含む統合検査は次のタスクで実行します.

```bash
uv run poe test
uv run poe check
```

## 本番環境への導入

固定された依存関係からCLI, ネイティブ拡張wheel, バックエンドwheel, フロントエンド静的ファイルを生成します.

```bash
uv run --frozen poe build
```

生成物は次の場所に出力されます.

- CLI: `target/release/bibmgr`
- Native wheel: `dist/native/*.whl`
- Backend wheel: `dist/backend/*.whl`
- Frontend static files: `frontend/dist/`

ソースチェックアウトからバックエンドを起動する場合は, lockfileを変更せず環境を同期してから, reloadを行わない本番運用向けタスクを実行します.

```bash
uv sync --frozen
HOST=0.0.0.0 PORT=8000 uv run --frozen poe start-backend
```

wheelだけを実行ホストへ導入する場合は, Python 3.12環境へネイティブ拡張wheelとバックエンドwheelをインストールして起動します.

```bash
uv venv --python 3.12 .venv-runtime
uv pip install \
  --python .venv-runtime/bin/python \
  dist/native/*.whl \
  dist/backend/*.whl
.venv-runtime/bin/python -m uvicorn bibmgr_backend.app:app \
  --host 0.0.0.0 \
  --port 8000
```

`frontend/dist/` は静的ファイルサーバまたはCDNから配信し, `/api/`をバックエンドへ転送するリバースプロキシを構成します.
