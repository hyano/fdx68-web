# デプロイと運用

このドキュメントは**開発中の反復デプロイ**（macOS から実機へ）について書いています。
第三者が素の Raspberry Pi OS に導入する手順は [installation.md](installation.md) を参照してください。

---

## 開発時のデプロイは rsync

Raspberry Pi に git が入っていないこと、そして編集のたびにコミットしたくないことから、
開発中は **macOS から rsync** で転送します。

```bash
./scripts/deploy.sh
```

スクリプトの動作:

```
1. ./scripts/test.sh を実行（失敗したらデプロイを中止）
2. rsync でソースを転送
3. 初回のみ venv を作成し、pip install -e . を実行
4. イメージディレクトリを作成（既存なら何もしない）
5. sudo systemctl restart fdx68-web
6. /api/health で疎通確認
```

接続先は `.env.deploy` から読み込みます（git 管理外）。
**接続先をスクリプトにハードコードしないでください。** 公開リポジトリに
自宅の接続情報を残さないためです。

### 転送対象から除外するもの

```
.venv/  __pycache__/  .git/  .env  .env.deploy  *.log
```

`--delete` を使いますが、対象はデプロイ先ディレクトリ
（`.env.deploy` の `DEPLOY_DIR`）のみです。

**イメージディレクトリ（`$HOME/fdximg`）は転送対象外です。**
デプロイ先とイメージ置き場を物理的に分けているのは、
`--delete` でディスクイメージを誤って消さないためです。

---

## ログの確認

```bash
./scripts/logs.sh
```

以下をまとめて取得します。

- `systemctl status fdx68-web`
- `journalctl -u fdx68-web -n 200`
- `pgrep -a fddemu`（fddemu が動いているか）
- `fddctl -l`（現在のドライブ状態）

---

## systemd サービス

`systemd/fdx68-web.service.in` をテンプレートとし、`install.sh` が
実行ユーザーとパスを埋めて `/etc/systemd/system/fdx68-web.service` に設置します。

主な設定:

```ini
[Service]
User=<インストール時に検出したユーザー>
WorkingDirectory=<リポジトリのパス>
ExecStart=<リポジトリのパス>/.venv/bin/uvicorn app.main:app --host ... --port ...
Restart=on-failure

Environment=LANG=C.UTF-8
Environment=PYTHONUTF8=1
Environment=PYTHONIOENCODING=utf-8
Environment=PYTHONUNBUFFERED=1
```

### ロケールを unit 内で固定している理由

Debian の `/etc/default/locale` は **PAM 経由のログインセッションに適用**されるもので、
systemd のシステムサービスには自動的には渡りません。

ロケールが `C` のままだと Python のファイルシステムエンコーディングが期待通りにならず、
**日本語ファイル名の FDX イメージを扱う際に破綻しうる**ためです
（X68000 のソフトはディレクトリ名を日本語で管理することが多い）。

`C.UTF-8` を選んでいるのは、`en_US.UTF-8` や `ja_JP.UTF-8` と違って
**ロケール生成の有無に依存せず常に利用可能**で、かつ UTF-8 が保証されるためです。
表示言語はアプリ側で持っているので、システムロケールに合わせる必要はありません。

この設定は「システム側のロケール設定が変わってもアプリの動作を変えない」ためのものです。
実際、本環境のロケールは開発中に `en_GB.UTF-8` から `en_US.UTF-8` へ変更されました。

### 起動時の自動起動について

`fdx68-web` サービス自体は自動起動します（`systemctl enable`）。

**ただし `fddemu` は自動起動しません。** Web UI から明示的に起動します。
Pi の電源を入れただけで X68000 からドライブが見える状態になると、
実機側の状態を意図せず変えてしまうためです。

---

## sudoers の設定

Web アプリは非 root で動作し、root 権限が必要な操作だけ `sudo -n` で実行します。

`install.sh` が `packaging/fdx68-web.sudoers.in` から生成し、
**`visudo -c` で構文検証してから** `/etc/sudoers.d/fdx68-web` に設置します
（構文エラーのある sudoers ファイルを置くと sudo 自体が使えなくなるため）。

```
<ユーザー> ALL=(root) NOPASSWD: /usr/local/bin/fddemu
<ユーザー> ALL=(root) NOPASSWD: /usr/bin/pkill -x fddemu
<ユーザー> ALL=(root) NOPASSWD: /sbin/reboot
<ユーザー> ALL=(root) NOPASSWD: /sbin/poweroff
```

`fddctl` は含めていません。**root 権限を必要としないことを実機で確認済み**のため、
不要な昇格をしない方針にしています。

### 既存の NOPASSWD ALL について

Raspberry Pi OS の既定では、初期ユーザーに `NOPASSWD: ALL` が設定されています
（`/etc/sudoers.d/010_pi-nopasswd` 等）。

Web アプリが動くホストとしてはこの権限は広すぎますが、
**これを削るかどうかは利用者の判断**です。削ると `sudo` のたびにパスワードが必要になり、
他の作業に影響します。

本プロジェクトが設置する `/etc/sudoers.d/fdx68-web` は、
既存の設定を変更せず、必要なコマンドを明示的に列挙するだけです。
既存の NOPASSWD ALL を削った場合でも本アプリが動作するようにするためのものです。

---

## セキュリティ上の注意

**このアプリケーションには認証機能がありません。**

以下の操作が誰でも実行できる状態になります。

- ディスクイメージの削除・上書き
- Raspberry Pi の再起動・シャットダウン
- fddemu の停止（X68000 のディスクアクセスが中断される）

家庭内 LAN の中だけで使ってください。
ルータのポート開放、UPnP、リバースプロキシによる外部公開は行わないでください。

外部からアクセスしたい場合は、VPN で LAN に接続する方式を推奨します
（アプリの前段に認証を置くより確実です）。

`FDX68_HOST` を `127.0.0.1` にすると、Pi 自身からしかアクセスできなくなります。
SSH ポートフォワード経由で使う場合はこの設定にしてください。

---

## トラブルシューティング

### サービスが起動しない

```bash
sudo systemctl status fdx68-web
sudo journalctl -u fdx68-web -n 50
```

よくある原因:

- `.env` の `FDX68_IMAGE_DIR` が存在しない、または権限がない
- venv が壊れている（`.venv` を削除して `install.sh` を再実行する）

### `fddctl` が「Can't connect to emulator process」を返す

`fddemu` が起動していません。Web UI の `[Start]` から起動してください。
これはエラーではなく正常な状態として扱われ、UI には「Stopped」と表示されます。

### 日本語のファイル名が文字化けする

systemd unit の `Environment=LANG=C.UTF-8` が設定されているか確認してください。

```bash
sudo systemctl show fdx68-web -p Environment
```

**対話 SSH では正常に見えてもサービス側で化けることがあります。**
両者はロケールが異なるため、必ずサービス側で確認してください。

### ディスクイメージを操作しようとすると 409 が返る

そのイメージが Drive 0 または Drive 1 に挿入されています。
先に排出してから操作してください。これは意図的なガードです。
