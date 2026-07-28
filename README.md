# ![BibMgR Logo](docs/assets/bibmgr-logo.png)

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

BibTeX検証をCLIツールとして使用したい場合は, GitHubから直接インストールできます. repositoryのcloneは不要です. CLIの実行ファイル名は`bibmgr`です.

```bash
cargo install --git https://github.com/EhimeNLP/bibmgr.git --locked bibmgr-cli
bibmgr --version
```

更新時は`--force`を付けて再インストールします.

```bash
cargo install --git https://github.com/EhimeNLP/bibmgr.git --locked --force bibmgr-cli
```

開発や内容確認のためにrepositoryをcloneする場合は, ローカルpathからもインストールできます.

```bash
git clone https://github.com/EhimeNLP/bibmgr.git
cd bibmgr
cargo install --locked --path crates/bibmgr-cli
```

ローカルcheckoutから更新する場合は, checkoutを更新してから再インストールします.

```bash
git pull
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

文献ライブラリAPIにはPostgreSQL 18を使用します. メール認証の開発用受信箱にはMailpitを使用します. Dockerが利用できる環境では両サービスを起動し, マイグレーションを適用します.

```bash
uv run poe dev-services-up
uv run poe db-migrate
```

Mailpitの受信箱は`http://127.0.0.1:8025/`で確認できます. 開発バックエンドは未設定時に`127.0.0.1:1025`へ認証メールを送信します.

Dockerは必須ではありません. macOSではPostgreSQL 18とMailpitをHomebrewで直接起動できます. ローカルDBの作成、初回アカウント作成、BibTeX登録、サービス停止までの手順は[`docs/local-development.md`](docs/local-development.md)を参照してください.

開発DBを空の最新schemaへ戻す場合は次を実行し, 表示されたDB名を入力して確認します. リモートDBに対するresetは拒否されます.

```bash
uv run poe db-reset
```

接続先は`BIBMGR_DATABASE_URL`で変更できます. 未設定時は`postgresql+psycopg://bibmgr:bibmgr@127.0.0.1:5432/bibmgr`を使用します. 登録ポリシーはサーバー側の`BIBMGR_REGISTRATION_POLICY`で選択し, 未設定時は原文保存用の`archive`です. 研究室ルールは登録時ではなくexport時に適用します. ログイン可能なメールドメインは未設定時に`ai.cs.ehime-u.ac.jp`です.

```bash
BIBMGR_DATABASE_URL=postgresql+psycopg://user:password@db.example/bibmgr \
BIBMGR_REGISTRATION_POLICY=archive \
uv run poe db-migrate
```

バックエンドとフロントエンドの開発サーバを同時に起動します.

```bash
uv run poe dev
```

- Frontend: `http://127.0.0.1:5173/`
- Backend: `http://127.0.0.1:8000/`
- Health check: `http://127.0.0.1:8000/healthz`
- Readiness check: `http://127.0.0.1:8000/readyz`
- API documentation: `http://127.0.0.1:8000/docs`
- Development email inbox: `http://127.0.0.1:8025/`

ログイン後の`History`画面では, 編集・削除を含む文献ごとの連番revisionを確認できます. 削除済み文献も履歴一覧に残り, 過去状態を選択して確認後に復元できます. 復元は既存履歴を変更せず, 新しいrevisionとして追加されます.

研究室ドメイン外の利用者は`BIBMGR_AUTH_ALLOWED_EMAILS`へ完全なメールアドレスを個別に追加します. ドメイン指定やワイルドカードでは許可されません.

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

本番向けのPostgreSQL 18, migration job, backend, Vue/Caddy構成は`compose.production.yaml`にあります.

```bash
cp .env.production.example .env.production
docker compose --env-file .env.production \
  -f compose.production.yaml up --detach --build --wait
```

本番バックエンドでは`BIBMGR_ENV=production`, secret file, SMTP接続情報, secure cookie, HTTPSを必須とします. アカウント管理, 認証データの定期削除, 監視, backup/restore, systemd timerを含む手順は[`docs/operations.md`](docs/operations.md), 認証仕様は[`docs/authentication.md`](docs/authentication.md)を参照してください.
