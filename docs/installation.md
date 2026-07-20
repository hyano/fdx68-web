# インストール手順

素の Raspberry Pi OS に FDX68 Web Controller を導入する手順です。

---

## メンテナンス担当者へ

**機能を追加したら、このドキュメントとインストーラも同じ PR で更新してください。**

| 変更内容 | 同時に更新するもの |
|---|---|
| 環境変数を追加した | `.env.example` / `app/config.py` / `install.sh` の生成ロジック / `README.md` |
| FDX68 コマンドへの依存を追加した | `install.sh` の前提条件検査 |
| FDX68 の新版に対応した | `packaging/fdx68-source.conf` の 3 値 / `CHANGELOG.md` |
| 必要なシステムパッケージが増えた | `install.sh` の依存導入 / このドキュメントの「前提条件」 |

---

## 前提条件

| 項目 | 要件 |
|---|---|
| ハードウェア | Raspberry Pi 3 Model A/B/B+ または Zero 2 W（FDX68 の推奨構成） |
| OS | Raspberry Pi OS **Bookworm** または **Trixie**（32bit / 64bit いずれも可） |
| Python | 3.11 以上 |
| FDX68 専用シールド | **必須**（ソフトからは検査できないため、インストーラが所有を確認します） |

Raspberry Pi 4 は FDX68 公式では非推奨（環境調整の上で使用可）、
Raspberry Pi 2 / Zero / Zero W / 5 は FDX68 が対応していません。

FDX68 本体が未導入でも構いません。インストーラが公式サイトから取得します。

---

## インストール

```bash
sudo apt install -y git
git clone https://github.com/hyano/fdx68-web.git
cd fdx68-web
./scripts/install.sh
```

インストーラは環境を検出し、**変更内容を提示してから確認を求めます**。

### git が使えない場合

Raspberry Pi OS Lite には git が入っていないことがあります。
apt を使わずに導入する場合は、GitHub Release の tarball を取得してください。

```bash
curl -L -o fdx68-web.tar.gz https://github.com/hyano/fdx68-web/archive/refs/heads/main.tar.gz
tar xzf fdx68-web.tar.gz
cd fdx68-web-main
./scripts/install.sh
```

ただし、この方法だとアップデートが `git pull` でできなくなるため、
可能であれば git を入れることを推奨します。

### インストーラのオプション

| オプション | 説明 |
|---|---|
| `--dry-run` | 実行計画を表示するだけで、何も変更しない |
| `--yes` | 対話的な確認をスキップする（ライセンス同意を除く） |
| `--uninstall` | サービスと設定を削除する |
| `--i-own-fdx68-shield` | FDX68 専用シールドの所有を明示的に宣言する（非対話インストール用） |
| `--upgrade-fdx68` | 導入済みの FDX68 を最新版に更新する |
| `--fdx68-url URL` | FDX68 のダウンロード元を指定する |
| `--skip-checksum` | SHA256 の照合を省略する（非推奨） |

### インストーラが行うこと

```
1. 環境検出       OS コードネーム、アーキテクチャ、Pi のモデル、Python バージョン
2. FDX68 検査     未導入なら同意確認のうえ公式サイトから取得・導入
                  導入済みならバージョンを表示するだけで触らない
3. 依存導入       python3-venv が無ければ apt install（実行前に確認）
4. 実行ユーザー   install.sh を実行したユーザーを自動検出
5. 仮想環境       リポジトリ内に .venv を作成し pip install
6. イメージ置き場 $HOME/fdximg を作成（既存なら中身に一切触れない）
7. .env 生成      検出値を埋めて生成（既存の .env は上書きしない）
8. sudoers        visudo -c で構文検証してから /etc/sudoers.d/fdx68-web に設置
9. systemd        unit を生成・設置して enable --now
10. 疎通確認      /api/health を確認し、アクセス URL を表示
```

---

## FDX68 の自動インストールについて

FDX68 が見つからない場合、インストーラは次のように確認します。

```
FDX68 本体が見つかりませんでした。
公式サイトからダウンロードしてインストールできます。

FDX68 のソフトウェアは、専用シールド(変換基板)を購入された方に限り
使用が許諾されています。

FDX68 専用シールドをお持ちですか？ [y/N]
```

**`--yes` を指定してもこの質問は自動承諾されません。**
非対話でインストールする場合は `--i-own-fdx68-shield` を明示的に指定してください。
ライセンス同意を、意図しないまま通過させないためです。

導入の手順:

```
1. 専用シールドの所有確認
2. アーキテクチャ判定（uname -m）
3. tarball のダウンロード
4. SHA256 の照合（不一致なら中止）
5. 一時ディレクトリに展開し、VERSION でバージョン確認
6. バイナリの ELF クラスを検証し、OS と一致しなければ中止
7. /usr/local/bin へ配置
8. fddemu -h でバージョンが表示されることを確認
```

**手順 6 が重要です。** 後述のとおり配布 URL の構成に癖があるため、
URL の命名を信用せず、実際のバイナリのアーキテクチャを検証してから配置します。

**既に FDX68 が導入済みの場合は何もしません。** バージョンを表示するだけです。
更新したい場合は `--upgrade-fdx68` を指定してください。
その際、fddemu が停止していることを確認します
（エミュレーション中にバイナリを差し替えると実機のディスクアクセスが壊れるため）。

### 配布元の設定と更新手順

FDX68 の配布 URL には次の特徴があります（実測で確認）。

- 固定 URL `fdx68.tar.gz` の中身は **32bit（armhf）版**
- **64bit 版に固定 URL は存在しない**。`fdx68_210_aarch64.tar.gz` のように
  バージョン番号付きの URL でのみ提供される
- 配布は **HTTP（平文）**

そのため、新版が出るたびに URL の更新が必要です。
定義は `packaging/fdx68-source.conf` の 1 ファイルに集約してあり、
**`install.sh` 本体を書き換える必要はありません。**

```sh
FDX68_VERSION="2.10"
FDX68_BASE_URL="http://retropc.net/gimons/fdx68"

FDX68_URL_aarch64="${FDX68_BASE_URL}/fdx68_210_aarch64.tar.gz"
FDX68_SHA256_aarch64="..."

FDX68_URL_armhf="${FDX68_BASE_URL}/fdx68.tar.gz"
FDX68_SHA256_armhf="..."
```

**新版への対応手順:**

1. 公式サイト（http://retropc.net/gimons/fdx68/）で新バージョンを確認する
2. `packaging/fdx68-source.conf` のバージョンと URL を更新する
3. tarball をダウンロードして SHA256 を記録する
   ```bash
   curl -sO http://retropc.net/gimons/fdx68/fdx68_XXX_aarch64.tar.gz
   sha256sum fdx68_XXX_aarch64.tar.gz
   ```
4. 実機で `--upgrade-fdx68` を実行して導入を確認する
5. `CHANGELOG.md` に記載する

なお、**リポジトリに tarball を取り込むことや GitHub Release へのミラーは行いません**
（再配布に当たるため）。ダウンロードは常に公式サイトから行います。

---

## インストーラを使わない手動インストール

インストーラが未知の環境で失敗した場合に備えた手順です。

### 1. FDX68 の導入

公式サイトから、**OS のビット数に合った**アーカイブをダウンロードします。

```bash
# 64bit の場合（uname -m が aarch64）
curl -O http://retropc.net/gimons/fdx68/fdx68_210_aarch64.tar.gz
mkdir -p /tmp/fdx68 && tar xzf fdx68_210_aarch64.tar.gz -C /tmp/fdx68

# アーキテクチャを確認（重要）
file /tmp/fdx68/fddemu

sudo cp /tmp/fdx68/{fddemu,fddctl,fdxconv,fdxtool,fdxview,fdxtrkcpy,fddump,fdrestore,fdunformat,fdinfo} /usr/local/bin/
sudo cp /tmp/fdx68/*.wav /usr/local/bin/
sudo chmod 755 /usr/local/bin/fd*
sudo chmod 644 /usr/local/bin/*.wav
```

### 2. 依存パッケージ

```bash
sudo apt install -y python3-venv
```

### 3. 仮想環境とアプリケーション

```bash
cd ~/fdx68-web
python3 -m venv .venv
.venv/bin/pip install -e .
mkdir -p ~/fdximg
cp .env.example .env
```

`.env` を編集し、`FDX68_BACKEND=real` と `FDX68_IMAGE_DIR` を自分の環境に合わせます。

### 4. sudoers

```bash
sudo visudo -f /etc/sudoers.d/fdx68-web
```

```
<ユーザー名> ALL=(root) NOPASSWD: /usr/local/bin/fddemu
<ユーザー名> ALL=(root) NOPASSWD: /usr/bin/pkill -x fddemu
<ユーザー名> ALL=(root) NOPASSWD: /sbin/reboot
<ユーザー名> ALL=(root) NOPASSWD: /sbin/poweroff
<ユーザー名> ALL=(root) NOPASSWD: /usr/bin/systemctl --no-block restart fdx68-web.service
```

`visudo` を使うのは、構文エラーのある sudoers ファイルを置くと
sudo 自体が使えなくなるためです。直接エディタで書かないでください。

### 5. systemd

`systemd/fdx68-web.service.in` を参考に unit を作成します。

```bash
sudo cp /tmp/fdx68-web.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fdx68-web
```

### 6. 確認

```bash
curl http://localhost:8000/api/health
```

---

## アップデート

```bash
cd ~/fdx68-web
git pull
./scripts/install.sh
```

インストーラは冪等なので、再実行がそのままアップデート手順になります。

**`.env` とイメージディレクトリの中身は変更されません。**
`.env.example` に新しい項目が追加されていた場合は、
`.env.new` として書き出され、差分が表示されます。

---

## アンインストール

```bash
./scripts/install.sh --uninstall
```

削除されるもの:

- `fdx68-web` サービス（停止・無効化・unit ファイルの削除）
- `/etc/sudoers.d/fdx68-web`

**削除されないもの:**

- **イメージディレクトリ（`~/fdximg`）とその中身**
- `.env`
- FDX68 本体（`/usr/local/bin` の各コマンド）
- リポジトリのディレクトリ

ディスクイメージは代替不能な資産なので、インストーラが消すことはありません。
不要であれば手動で削除してください（パスは実行時に表示されます）。

---

## クリーン環境での検証（メンテナンス担当者向け）

既存環境での再実行では冪等性しか確認できません。
**素の環境での動作確認には予備の SD カードが必要です。**

```
[ ] Raspberry Pi Imager で Raspberry Pi OS を新規書き込み
    （Bookworm と Trixie の両方で確認するのが望ましい）
[ ] 初回起動でユーザーを作成する（pi 以外の名前にして、ユーザー名の自動検出を確認する）
[ ] sudo apt install -y git
[ ] git clone してから ./scripts/install.sh
[ ] FDX68 未導入の状態から、シールド所有確認 → ダウンロード → 導入まで通ること
[ ] シールド所有確認に N と答えた場合、FDX68 を導入せず中止すること
[ ] --yes 単独ではシールド所有確認を通過できないこと
[ ] サービスが起動し、別の PC のブラウザからアクセスできること
[ ] もう一度 ./scripts/install.sh を実行し、何も壊れないこと
[ ] --uninstall でサービスが消え、イメージディレクトリと FDX68 が残ること
```

アーキテクチャ検証の確認（誤ったバイナリを配置しないこと）:

```
[ ] 64bit 環境で FDX68_URL_OVERRIDE に 32bit 版の URL を指定する
[ ] /usr/local/bin に配置される前に、アーキテクチャ不一致として中止されること
[ ] SHA256 を意図的に書き換え、照合失敗で中止されること
```

---

## トラブルシューティング

### 「FDX68 が見つかりません」と表示される

FDX68 が未導入です。インストーラの指示に従って導入するか、
手動インストールの手順 1 を実行してください。

導入済みなのに検出されない場合は、`PATH` を確認してください。
インストーラは `PATH` と `/usr/local/bin` を探します。

### 「SHA256 が一致しません」と表示される

考えられる原因:

- ダウンロードが途中で壊れた（再実行してください）
- 上流が同じ URL の内容を差し替えた（`packaging/fdx68-source.conf` の更新が必要です）
- 通信経路で改ざんされた（配布が HTTP のため、可能性としては残ります）

`--skip-checksum` で照合を飛ばせますが、
**バイナリは root 権限で `/dev/mem` を触るソフトウェアです。** 安易に使わないでください。

### 「アーキテクチャが一致しません」と表示される

ダウンロードした FDX68 が、実行中の OS と異なるビット数のものです。

64bit OS（`uname -m` が `aarch64`）に 32bit のバイナリを置いても、
`/lib/ld-linux-armhf.so.3` が存在しないため起動しません。
インストーラが配置前に検出して中止しています。

`packaging/fdx68-source.conf` の URL が正しいか確認してください。

### サービスが起動しない

```bash
sudo systemctl status fdx68-web
sudo journalctl -u fdx68-web -n 50
```

よくある原因は、`.env` の `FDX68_IMAGE_DIR` が存在しないか、権限がないことです。

### 権限エラーが出る（fddemu が起動できない）

`/etc/sudoers.d/fdx68-web` が正しく設置されているか確認してください。

```bash
sudo -n /usr/local/bin/fddemu -h
```

これがパスワードを要求する場合、sudoers の設定が効いていません。

なお `fddctl` は root 権限を必要としないため、sudoers には含めていません。
`fddctl -l` は一般ユーザーのまま実行できます。

### 日本語のファイル名が文字化けする

systemd unit のロケール設定を確認してください。

```bash
sudo systemctl show fdx68-web -p Environment
```

`LANG=C.UTF-8` と `PYTHONUTF8=1` が含まれている必要があります。

**対話 SSH では正常に見えてもサービス側で化けることがあります。**
両者はロケールが異なるため、必ずサービス側で確認してください。

### Web UI にアクセスできない

```bash
# サービスが待ち受けているか
ss -tlnp | grep 8000

# Pi の IP アドレス
hostname -I
```

`.env` の `FDX68_HOST` が `127.0.0.1` になっていると、
Pi 自身からしかアクセスできません。
