# Local development

BibMgRの開発環境には、アプリケーション本体に加えて次の2サービスが必要です。

- PostgreSQL: ユーザー、セッション、文献、操作履歴の保存
- Mailpit: 開発中に送信されるログインコードの捕捉

Dockerはこれらを起動するための選択肢の1つであり、アプリケーションの必須要件ではありません。Dockerを使わない場合は、同じサービスをローカルPCへ直接インストールします。

## Dockerを使用する場合

PostgreSQLとMailpitを起動し、DBマイグレーションを適用します。

```bash
uv run poe dev-services-up
uv run poe db-migrate
uv run poe dev
```

## Dockerを使用しないmacOS環境

Homebrewを使ってPostgreSQL 18とMailpitをインストールします。

```bash
brew install postgresql@18 mailpit
brew services start postgresql@18
brew services start mailpit
```

`postgresql@18`はkeg-onlyのため、コマンドを実行するシェルでバイナリの場所を`PATH`へ追加します。

```bash
export PATH="/opt/homebrew/opt/postgresql@18/bin:$PATH"
```

開発用のロールとDBを作成します。

```bash
createuser --login --pwprompt bibmgr
createdb --owner=bibmgr bibmgr
```

パスワードの入力を求められたら、デフォルト接続設定に合わせて`bibmgr`を指定します。別のパスワードを使う場合は、アプリケーションを起動するシェルで接続先を設定してください。

```bash
export BIBMGR_DATABASE_URL="postgresql+psycopg://bibmgr:your-password@127.0.0.1:5432/bibmgr"
```

マイグレーションを適用し、バックエンドとフロントエンドを起動します。

```bash
uv run poe db-migrate
uv run poe dev
```

## 動作確認

起動後は次のURLを使用します。

- Frontend: `http://127.0.0.1:5173/`
- Backend: `http://127.0.0.1:8000/`
- Backend readiness: `http://127.0.0.1:8000/readyz`
- Mailpit inbox: `http://127.0.0.1:8025/`

初回ログインでは、`dev@ai.cs.ehime-u.ac.jp`のように許可ドメインを持つ開発用アドレスを入力します。Mailpitはメールを外部へ配送せずローカルで捕捉するため、このアドレスの実在は要求されません。Mailpitの受信箱で8桁のコードを確認して入力すると、初回検証時にアカウントが作成されます。ログイン後は、追加ボタンからBibTeXを登録できます。

検索、BibTeX解析、修正候補の計算、exportなどの読み取り専用操作はログインなしでも利用できます。文献の登録、編集、削除、復元にはログインが必要です。

研究室ドメイン外の開発用アドレスを試す場合は、完全なアドレスを明示します。次の設定は`visitor@example.org`だけを追加し、同じドメインの別アドレスは許可しません。

```bash
export BIBMGR_AUTH_ALLOWED_EMAILS="visitor@example.org"
uv run poe dev
```

## サービスの停止

Docker Composeで起動した場合:

```bash
docker compose down
```

Homebrew servicesで起動した場合:

```bash
brew services stop mailpit
brew services stop postgresql@18
```

停止してもPostgreSQLのデータは残ります。開発DBを空の最新schemaへ戻す場合は、ローカルDBを対象に次を実行し、表示されたDB名を入力して確認します。

```bash
uv run poe db-reset
```

## 外部サービスを使用する場合

ローカルPCにPostgreSQLやMailpitをインストールせず、既存のPostgreSQLとSMTPリレーを指定することもできます。

```bash
export BIBMGR_DATABASE_URL="postgresql+psycopg://user:password@db.example/bibmgr"
export BIBMGR_SMTP_HOST="smtp.example"
export BIBMGR_SMTP_PORT="587"
export BIBMGR_SMTP_USERNAME="smtp-user"
export BIBMGR_SMTP_PASSWORD="smtp-password"
export BIBMGR_SMTP_STARTTLS="true"

uv run poe db-migrate
uv run poe dev
```

実在するSMTPリレーを使用する場合、ログインコードは入力したメールアドレスへ実際に送信されます。認証情報はリポジトリへ保存しないでください。

## ローカルでのバックアップ

PostgreSQL client 18の`pg_dump`が`PATH`にある状態で次を実行すると、`backups/`に権限`0600`のcustom-formatバックアップを作成します。

```bash
uv run poe db-backup
```

復元は現在のDB内容を置き換えるため、入力ファイルと対象DB名を明示します。

```bash
uv run bibmgr-ops restore \
  --input backups/bibmgr-YYYYMMDDTHHMMSSZ.dump \
  --confirm-database bibmgr
```
