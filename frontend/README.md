# Vue 3 + TypeScript + Vite

This template should help get you started developing with Vue 3 and TypeScript in Vite. The template uses Vue 3 `<script setup>` SFCs, check out the [script setup docs](https://v3.vuejs.org/api/sfc-script-setup.html#sfc-script-setup) to learn more.

Learn more about the recommended Project Setup and IDE Support in the [Vue Docs TypeScript Guide](https://vuejs.org/guide/typescript/overview.html#project-setup).

# Frontend

## 概要

本ディレクトリでは，`bibmgr` のフロントエンド部分を実装する。

`bibmgr` は，研究室の過去論文から参考文献を抽出し，BibTeXの登録・検索・再利用を支援するWebアプリである。フロントエンドでは，文献検索，文献一覧表示，文献詳細表示，BibTeX表示，引用文脈表示などのUIを提供する。

現時点では，バックエンド，データベース，検索処理，データ形式が未確定であるため，フロントエンド側では仮のデータ型と仮のAPI関数を用意している。実際の検索処理やデータベース接続は行わず，バックエンド実装後にAPI接続部分を差し替える前提で作成している。

## 使用技術

* Vue
* TypeScript
* Vite
* npm

## 現在実装済みの機能

現在，以下のフロントエンド基盤を実装している。

* Vue + TypeScript + Vite によるフロントエンド環境の構築
* アプリケーション全体のレイアウト作成
* ヘッダー表示
* 文献検索用のクエリ入力欄
* 文献一覧表示エリア
* 文献詳細表示エリア
* BibTeX表示エリア
* 引用文脈表示エリア
* Empty状態の表示
* Loading状態の表示
* Error状態の表示
* 文献データの仮型定義
* バックエンドAPI接続用の仮関数

現時点では，検索を実行してもバックエンドには接続されず，空配列が返る。そのため，初期状態ではデータベースが空であることを示す表示が出る。

## ディレクトリ構成

```text
frontend/
├─ package.json
├─ package-lock.json
├─ vite.config.ts
├─ tsconfig.json
├─ tsconfig.app.json
├─ tsconfig.node.json
├─ index.html
├─ public/
└─ src/
   ├─ main.ts
   ├─ App.vue
   ├─ style.css
   ├─ types/
   │  └─ reference.ts
   ├─ api/
   │  └─ references.ts
   └─ components/
      ├─ SearchBar.vue
      ├─ ReferenceList.vue
      ├─ ReferenceCard.vue
      ├─ ReferenceDetail.vue
      ├─ EmptyState.vue
      └─ LoadingState.vue
```

なお，`dist/` は `npm run build` によって生成されるビルド成果物であり，通常はGit管理に含めない。

## 各ファイルの役割

### `src/main.ts`

Vueアプリケーションのエントリーポイントである。
`App.vue` を読み込み，`index.html` 内の `#app` にVueアプリをマウントする。

### `src/App.vue`

アプリケーション全体のメイン画面である。
検索欄，文献一覧，文献詳細表示を配置し，以下の状態を管理する。

* 検索クエリ
* 文献一覧
* 選択中の文献
* Loading状態
* Error状態
* 検索実行済みかどうか

### `src/style.css`

アプリケーション全体のスタイルを定義する。
ヘッダー，検索欄，2カラムレイアウト，文献カード，詳細表示，Empty表示，Loading表示，Error表示などの見た目を管理する。

### `src/types/reference.ts`

フロントエンドで使用する文献データの仮型定義を行う。

現在は以下のようなデータ構造を想定している。

```ts
export type CitationContext = {
  id: string;
  sourcePaperTitle?: string;
  sourceFileName?: string;
  before?: string;
  context: string;
  after?: string;
};

export type Reference = {
  id: string;
  title: string;
  authors: string[];
  year?: number;
  venue?: string;
  doi?: string;
  url?: string;
  bibtexKey?: string;
  bibtex?: string;
  citationContexts?: CitationContext[];
};
```

バックエンド側で正式なデータ形式が決まった後，この型定義は必要に応じて修正する。

### `src/api/references.ts`

文献検索APIとの接続部分をまとめるファイルである。

現時点ではバックエンド未接続のため，検索クエリを受け取ったうえで空配列を返す仮実装になっている。

```ts
export async function searchReferences(query: string): Promise<Reference[]> {
  console.log("Search query:", query);
  return [];
}
```

バックエンドAPIが完成した後は，この関数を実際のAPI通信処理に差し替える。

### `src/components/SearchBar.vue`

検索入力欄のコンポーネントである。
検索文字列の入力と，検索ボタンまたはEnterキーによる検索イベントの発火を担当する。

実際の検索処理はこのコンポーネントでは行わず，親コンポーネントである `App.vue` に通知する。

### `src/components/ReferenceList.vue`

文献一覧を表示するコンポーネントである。
複数の文献データを受け取り，各文献を `ReferenceCard.vue` として表示する。

文献カードがクリックされた場合，選択された文献を親コンポーネントへ通知する。

### `src/components/ReferenceCard.vue`

文献1件分の情報をカード形式で表示するコンポーネントである。

現在は以下の項目を表示する。

* title
* authors
* year
* venue
* doi

### `src/components/ReferenceDetail.vue`

選択された文献の詳細情報を表示するコンポーネントである。

現在は以下の項目を表示する。

* Metadata
* BibTeX
* Citation Contexts

BibTeXが存在する場合は，Copyボタンでクリップボードにコピーできる。

### `src/components/EmptyState.vue`

データが存在しない場合の表示用コンポーネントである。

初期状態では，データベースが空であることを表示する。
検索後に結果が存在しない場合は，一致する文献が見つからなかったことを表示する。

### `src/components/LoadingState.vue`

読み込み中の表示用コンポーネントである。
バックエンドAPI接続後，検索処理中の状態表示として使用する。

## セットアップ方法

### 1. リポジトリをcloneする

```bash
git clone https://github.com/EhimeNLP/bibmgr.git
cd bibmgr
```

### 2. 使用するブランチに移動する

フロントエンド実装ブランチを確認・実行する場合は，以下を実行する。

```bash
git fetch origin
git checkout feat/vue-frontend-base
```

もしローカルに `feat/vue-frontend-base` が存在しない場合は，以下を実行する。

```bash
git checkout -b feat/vue-frontend-base origin/feat/vue-frontend-base
```

`feat/vue-frontend-base` が `dev` にマージ済みの場合は，以下のように `dev` ブランチを使用する。

```bash
git checkout dev
git pull origin dev
```

### 3. `frontend` ディレクトリに移動する

```bash
cd frontend
```

### 4. 依存パッケージをインストールする

```bash
npm install
```

## 起動方法

開発用サーバーを起動する。

```bash
npm run dev
```

起動後，以下のようなURLが表示される。

```text
http://localhost:5173/
```

このURLをブラウザで開くと，フロントエンド画面を確認できる。

## ビルド方法

本番用のビルドを作成する場合は，以下を実行する。

```bash
npm run build
```

ビルドが成功すると，`dist/` ディレクトリに本番用ファイルが生成される。ただし，`dist/` はビルド成果物であり，通常はGit管理に含めない。

## 現在の表示仕様

### 初期状態

バックエンドとデータベースが未接続のため，初期状態では以下のようなEmpty表示を行う。

```text
No references found
The database is currently empty. References will appear here after the backend and database are connected.
```

### 検索後に結果がない場合

検索を実行しても結果が存在しない場合，以下のような表示を行う。

```text
No matching references found
Try another keyword or check whether references have been registered.
```

### 文献未選択状態

文献詳細エリアでは，文献が選択されていない場合，以下を表示する。

```text
Select a reference to view details.
```

## 今後実装するもの

今後，以下の機能を実装する予定である。

* バックエンドAPIとの接続
* 実際の文献検索処理との接続
* データベースに保存された文献一覧の取得
* 文献詳細情報の取得
* BibTeX復元結果の表示
* 引用文脈抽出結果の表示
* 文献登録機能
* 文献編集機能
* 文献削除機能
* 検索条件の拡張
* エラー表示の改善
* UI/UXの改善
* 画面遷移が必要な場合のルーティング追加

## 今後設定が必要なもの

バックエンドやデプロイ方針が決定した後，以下の設定が必要になる。

### APIエンドポイント設定

バックエンドAPIのURLが決まり次第，`src/api/references.ts` を修正する。

例:

```ts
const response = await fetch(
  `/api/references?query=${encodeURIComponent(query)}`
);
```

開発環境と本番環境でAPIのURLが異なる場合は，環境変数を使用する。

例:

```env
VITE_API_BASE_URL=http://localhost:8000
```

### データ形式の調整

バックエンド側で正式なレスポンス形式が決まり次第，`src/types/reference.ts` の型定義を修正する。

特に以下の項目はバックエンド側の設計に合わせる必要がある。

* 文献ID
* title
* authors
* year
* venue
* doi
* BibTeX key
* BibTeX本文
* 引用文脈
* 元論文情報
* ファイル名
* 登録日時
* 更新日時

### ルーティング設定

複数画面構成にする場合は，`vue-router` の導入を検討する。

```bash
npm install vue-router
```

想定される画面は以下である。

* 文献一覧画面
* 文献詳細画面
* 文献登録画面
* 文献編集画面
* BibTeX確認画面
* 引用文脈確認画面

### 状態管理設定

文献データやユーザー情報など，複数コンポーネントで共有する状態が増えた場合は，`Pinia` の導入を検討する。

```bash
npm install pinia
```

現時点では状態管理が単純であるため，Vue標準の `ref` による管理で十分である。

### デプロイ設定

ホスティング方式が決まり次第，以下の設定を行う。

* 本番用ビルド設定
* API接続先の環境変数設定
* 静的ファイル配信設定
* CI/CD設定
* GitHub Actions設定

## 注意事項

現時点では，フロントエンドはバックエンド未接続である。
そのため，検索処理，データベース接続，文献登録，BibTeX復元，引用文脈抽出はまだ実行されない。

現在の実装は，後からバックエンドと接続するためのUI基盤である。
