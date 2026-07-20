# FDX68 Web Controller

X68000 実機に接続した **FDX68** を、Web ブラウザから操作するためのコントローラです。

Raspberry Pi に SSH でログインして `fddctl` を手打ちすることなく、
ブラウザからディスクイメージの挿入・排出・変換・整理ができます。
複数枚組ソフトのディスク交換を、X68000 の前に座ったまま完結させることを目的にしています。

---

## はじめにお読みください

**このソフトウェアは FDX68 のフロントエンドです。単体では動作しません。**
別途 **FDX68 専用シールド（変換基板）** と FDX68 本体が必要です。

FDX68 は GIMONS 氏が開発・頒布するハードウェアとソフトウェアの総称で、
ソフトウェアの使用許諾は専用シールドの購入者に限られています。

> FDX68 について: http://retropc.net/gimons/fdx68/

**このソフトウェアには認証機能がありません。インターネットに公開しないでください。**
ディスクイメージの削除や Raspberry Pi の再起動・シャットダウンを行える API を持つため、
家庭内 LAN の中だけで使うことを前提としています。
ルータのポート開放や UPnP による外部公開は行わないでください。

---

## できること

**FDD エミュレーション**

- fddemu の起動・停止
- Drive 0 / Drive 1 へのディスクイメージ挿入・排出
- ライトプロテクトの切り替え
- ドライブ状態（挿入中のイメージ、ライトプロテクト、シリンダ位置）のリアルタイム表示

**ディスクイメージの管理**

- Finder のようなツリー表示でのイメージ閲覧
- ドラッグ＆ドロップでのアップロード、および手元 PC へのダウンロード
- ドラッグ＆ドロップでのフォルダ間移動（Option 併用でコピー）
- 複製、リネーム、削除、新規フォルダ作成
- `.d88` `.xdf` `.hdm` などから FDX 形式への変換（`fdxconv`）
- 新規ブランクディスクイメージの作成（`fdxtool`）
- FDX のディスク情報表示、ディスク名・ライトプロテクト属性の編集

**システム操作**

- Raspberry Pi の再起動・シャットダウン（確認ダイアログ付き）

---

## 動作環境

| | 要件 |
|---|---|
| ハードウェア | Raspberry Pi 3 Model A/B/B+ または Zero 2 W（FDX68 の推奨構成） |
| OS | Raspberry Pi OS **Bookworm** または **Trixie**（32bit / 64bit いずれも可） |
| Python | 3.11 以上 |
| FDX68 | 2.10 以降 |

---

## インストール

```bash
sudo apt install -y git
git clone https://github.com/hyano/fdx68-web.git
cd fdx68-web
./scripts/install.sh
```

インストーラは環境を検出し、**変更内容を提示してから確認を求めます**。
FDX68 が未導入の場合は、専用シールドの所有を確認したうえで公式サイトから取得します。

インストール後、ブラウザで `http://<Raspberry Pi の IP アドレス>:8000` を開いてください。

詳細な手順、手動でのインストール方法、アップデート、アンインストール、
トラブルシューティングは [docs/installation.md](docs/installation.md) を参照してください。

---

## 設定

設定は `.env` で行います（`.env.example` をコピーして使います）。
インストーラが検出値を埋めた `.env` を生成するため、通常は編集不要です。

| 変数 | 既定値 | 説明 |
|---|---|---|
| `FDX68_BACKEND` | `mock` | `real` で実機のコマンドを実行、`mock` で開発用の模擬動作 |
| `FDX68_IMAGE_DIR` | `$HOME/fdximg` | ディスクイメージを置くディレクトリ。Web UI からはこの配下しか見えません |
| `FDX68_BIN_DIR` | `/usr/local/bin` | FDX68 のコマンドが置かれているディレクトリ |
| `FDX68_USE_SUDO` | `true` | root が必要なコマンド（fddemu / pkill / reboot / poweroff）を `sudo -n` 経由で実行するか |
| `FDX68_STATUS_INTERVAL` | `2` | ドライブ状態を取得する間隔（秒） |
| `FDX68_MAX_UPLOAD_MB` | `256` | アップロード 1 ファイルあたりの上限（MB） |
| `FDX68_FDDEMU_OPTIONS` | （空） | fddemu の起動オプション。空なら FDX68 の既定値 |
| `FDX68_AUTOSTART_FDDEMU` | `true` | Web UI 起動時に fddemu も自動起動するか |
| `FDX68_HOST` | `0.0.0.0` | 待ち受けアドレス |
| `FDX68_PORT` | `8000` | 待ち受けポート |

設定を変更したらサービスを再起動してください。

```bash
sudo systemctl restart fdx68-web
```

---

## 開発

開発は macOS 上で行い、実機の FDX68 コマンドを呼ばない **Mock バックエンド**で動作確認します。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

cp .env.example .env      # FDX68_BACKEND=mock のまま使う
uvicorn app.main:app --reload
```

```bash
./scripts/test.sh         # Unit → Integration → ruff → shellcheck
./scripts/deploy.sh       # 実機へ rsync して再起動（テストが通らなければ中止）
./scripts/logs.sh         # 実機のログとドライブ状態を取得
```

設計方針と各ドキュメントの位置づけは [docs/](docs/) と [CLAUDE.md](CLAUDE.md) を参照してください。

---

## ライセンス

本リポジトリのコードは **MIT License** です（[LICENSE](LICENSE)）。

**FDX68 本体は本ライセンスの対象ではありません。** FDX68 は GIMONS 氏が開発・頒布する
別のソフトウェアで、使用許諾は専用シールドの購入者に限られ、公式サイト以外での配布は
認められていません。本リポジトリには FDX68 のバイナリを一切含んでいません。

---

## 謝辞

FDX68 を開発・頒布されている GIMONS 氏に感謝します。
