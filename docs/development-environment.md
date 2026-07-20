# 開発環境

開発ホストは macOS、実行ターゲットは Raspberry Pi という**クロス開発**です。
macOS 上では実機の FDX68 コマンドを呼ばず、Mock バックエンドで開発します。

---

## 役割の分担

| macOS で行う | Raspberry Pi で行う |
|---|---|
| ソースコードの編集 | 実際の FDX68 コマンドの実行 |
| Unit Test / Integration Test | 実 FDD・X68000 との接続確認 |
| Mock バックエンドでの動作確認 | 実機統合テスト |
| 静的解析（ruff / shellcheck） | サービスとしての稼働 |

---

## 実測した環境

### macOS（開発ホスト）

| 項目 | 値 |
|---|---|
| OS | macOS 26.5.2 / arm64（Apple Silicon） |
| Python | 3.14.6（`/opt/homebrew/bin/python3`） |
| git | 2.55.0 |
| rsync | openrsync（protocol 29） |
| Homebrew | あり |
| uv / pyenv / docker | なし |

### Raspberry Pi（実行ターゲット）

| 項目 | 値 |
|---|---|
| モデル | Raspberry Pi 3 Model A Plus Rev 1.0 |
| OS | Debian GNU/Linux 13 (trixie) / aarch64 / kernel 6.18.34 |
| Python | 3.13.5（`python3-venv` 導入済、ensurepip に pip 25.1.1 同梱） |
| メモリ | **実装 415MB / 空き 275MB** |
| ディスク | 118GB 中 110GB 空き |
| git | **なし**（デプロイに rsync を使う理由） |
| rsync | `/usr/bin/rsync` |
| システムの pip | なし（venv 経由でのみ利用可） |
| sudo | NOPASSWD ALL |
| locale | `en_US.UTF-8`（`ja_JP.utf8` も生成済） |
| timezone | Asia/Tokyo |

---

## Python バージョンの互換性

| | Python |
|---|---|
| macOS（開発） | 3.14 系 |
| Raspberry Pi OS Trixie | 3.13 系 |
| Raspberry Pi OS Bookworm | 3.11 系 |

`pyproject.toml` で `requires-python = ">=3.11"` としています。
**Bookworm の 3.11 でも動く必要があるため、3.12 以降でしか使えない構文・API は使えません。**

ruff の `target-version = "py311"` でこれを機械的にチェックしています。

---

## セットアップ（macOS）

```bash
git clone <このリポジトリ>
cd fdx68-web

python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

cp .env.example .env          # FDX68_BACKEND=mock のまま使う
cp .env.deploy.example .env.deploy   # 実機の接続先を自分の環境に合わせて記入
```

`.env` と `.env.deploy` は git 管理外です。
**`.env.deploy` には接続情報を書くため、絶対にコミットしないでください。**

### 開発サーバの起動

```bash
uvicorn app.main:app --reload
```

`http://localhost:8000` で Web UI が開きます。

Mock バックエンドは、実際の FDX68 コマンドを呼ばずにメモリ上の状態を返します。
ドライブ操作・イメージ一覧・WebSocket 更新をひととおり確認できます。

イメージディレクトリは `.env` の `FDX68_IMAGE_DIR` で指定します。
macOS では `testdata/images` などローカルのディレクトリを指定してください。

### テスト

```bash
./scripts/test.sh
```

Unit Test → Integration Test → ruff → shellcheck の順に実行し、
いずれかが失敗した時点で非ゼロで終了します。

個別に実行する場合:

```bash
pytest tests/unit
pytest tests/integration
ruff check .
ruff format --check .
shellcheck scripts/*.sh
```

---

## Raspberry Pi への接続

接続先は `.env.deploy` に記述します（git 管理外）。
以下は例なので、自分の環境のホスト名・ユーザー名に置き換えてください。

```sh
DEPLOY_HOST=pi@raspberrypi.local
DEPLOY_DIR=/home/pi/fdx68-web
HEALTH_URL=http://raspberrypi.local:8000/api/health
```

**接続情報をリポジトリ内のファイルに書かないでください。**
`.env.deploy` は `.gitignore` に含まれています。

### SSH 鍵の設定（初回のみ）

`deploy.sh` と `logs.sh` を非対話で実行するには、公開鍵認証が必要です。

```bash
ssh-copy-id <ユーザー名>@<ホスト名>
```

パスワード認証のままだと、スクリプトの実行のたびにパスワードを求められます。
また、スクリプトにパスワードを埋め込むことは絶対にしないでください。

---

## エディタ設定

ruff がフォーマッタと linter を兼ねています。
エディタで保存時フォーマットを設定する場合は ruff を使ってください
（black や flake8 と併用すると設定が衝突します）。

```
line-length = 100
target-version = "py311"
```
