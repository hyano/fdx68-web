# FDX68 実機での実測メモ

公式ドキュメントの記述と、実機での実測結果の差異・補足を記録します。
**実装で判断に迷ったときは、公式サイトではなくこのファイルの内容を優先**してください。

対象環境:

| 項目 | 値 |
|---|---|
| FDX68 | 2.1.0（`VERSION` は `2.10`）/ Build Jun 5 2026 |
| ハードウェア | Raspberry Pi 3 Model A Plus Rev 1.0 |
| OS | Debian GNU/Linux 13 (trixie) / aarch64 / kernel 6.18.34 |
| 導入されているビルド | `fdx68_210_aarch64.tar.gz` |

---

## 確定済み

### ヘルプオプションはコマンドによって挙動が違う

- `fddemu -h` … 正常にヘルプを表示する
- `fddctl -h` … **何も出力しない**。引数なしで実行するとヘルプが出る
- `fdxconv -h` / `fdxtool -h` … `Error : Invalid ... file path` を出したうえでバナーだけ表示する。
  引数なしで実行するとヘルプが出る

**ヘルプの取得やバージョン確認には、引数なしでの実行を使う**のが確実です。
ただし `fddemu` は引数なしだとエミュレーションを開始してしまうため、`fddemu -h` を使います。

### エラー時でも終了コードが 0 になることがある

`fddemu` が停止している状態で `fddctl -l` を実行すると、
標準出力に以下が出ますが、終了コードは 0 でした。

```
Error : Can't connect to emulator process
```

**終了コードだけで成否を判定してはいけません。** 出力に `Error` が含まれるかどうかも
必ず確認してください（`app/command/parser.py` で実装）。

### 配布 URL はアーキテクチャによって事情が異なる

固定 URL `http://retropc.net/gimons/fdx68/fdx68.tar.gz` の中身は **32bit（armhf）版**です。

```
$ file fddemu
ELF 32-bit LSB executable, ARM, EABI5 version 1 (SYSV), dynamically linked,
interpreter /lib/ld-linux-armhf.so.3, for GNU/Linux 3.2.0, not stripped
```

**64bit 版の固定 URL は存在しません。** 以下はいずれも 404 でした。

```
fdx68_aarch64.tar.gz   404
fdx68-aarch64.tar.gz   404
fdx68_64.tar.gz        404
fdx68_arm64.tar.gz     404
```

64bit 版は `fdx68_210_aarch64.tar.gz` というバージョン番号付き URL でのみ提供されます。
新版が出るたびに URL の更新が必要です（`packaging/fdx68-source.conf` の 1 ファイルで完結する設計にしています）。

64bit Raspberry Pi OS に armhf バイナリを置いても `/lib/ld-linux-armhf.so.3` がないため
**起動しません**。インストーラは URL の命名を信用せず、展開したバイナリの ELF クラスを
実際に検証してから配置します。

### 配布はすべて HTTP（平文）

`https://retropc.net/` は利用できず、ダウンロードは HTTP で行うことになります。
取得したバイナリは root で `/usr/local/bin` に置かれ、`fddemu` は `/dev/mem` を直接触るため、
**インストーラは SHA256 を照合します**（`packaging/fdx68-source.conf`）。

実測した SHA256:

| ファイル | サイズ | SHA256 |
|---|---|---|
| `fdx68.tar.gz`（armhf, 2.10） | 443,550 | `1030249144b77ee8ea717b6473bad4824263734cdb5340f1134fa3c4360d29aa` |
| `fdx68_210_aarch64.tar.gz` | 486,301 | `a0972d82bd0d0ae8ef95b1387c50bbf5aa44bc4e3565382cbd97519b25f5fde5` |

aarch64 版については、**別々の時期・経路で取得した 2 つのコピーのハッシュが一致する**ことを
確認している。

- 2026-06-05 に Raspberry Pi へ導入した `~/fdx68_210_aarch64.tar.gz`
- 2026-07-20 に開発ホスト（macOS）から改めてダウンロードしたもの

配布が HTTP（平文）であるため単独のダウンロードでは真正性を確認できないが、
1 か月以上離れた 2 回の取得が同一バイト列であることは、経路上で改ざんされていないことの
裏付けになる。

展開して確認した内容:

```
$ cat VERSION
2.10
$ file fddemu
ELF 64-bit LSB pie executable, ARM aarch64, version 1 (SYSV), dynamically linked,
interpreter /lib/ld-linux-aarch64.so.1, for GNU/Linux 3.7.0, not stripped
```

### インストーラの検証分岐（確認済み）

`sudo` をダミーに差し替えた隔離環境で、以下の分岐が意図通り動作することを確認した
（いずれも `/usr/local/bin` には何も配置されないことを確認済み）。

| 条件 | 結果 |
|---|---|
| SHA256 が一致しない | 期待値と実際の値を示して中止する |
| 32bit 版を 64bit 環境に指定 | **配置前に**アーキテクチャ不一致として中止する |
| URL を上書きし、ハッシュを指定しない | 実際の値を表示して続行の確認を求める |
| URL・ハッシュとも正しい | 検証を通過し、配置へ進む |

### tarball はフラット構造

トップレベルディレクトリを持たず、ファイルが直接並んでいます。
展開時は必ず一時ディレクトリを指定してください。

```
fddctl fddemu fddump fdinfo fdrestore fdunformat fdxconv fdxtool fdxtrkcpy fdxview
readme VERSION fddseek.wav fddinsert.wav fddeject.wav
```

### `CL`（シリンダ）欄は 10 進表記

`fddctl -l` の `CL` 欄は 2 桁ゼロ埋めの **10 進**です（実機で確認済み）。
シリンダ 10 以上でも `0A` ではなく `10` と表示されます。

X68000 の 2HD は 77 シリンダなので、0〜79 の範囲では 10 進と 16 進の
見分けがつかない値が多く、確認するまで断定できませんでした。

パーサーは `int(cl_field, 10)` で解釈します。
ただし将来のバージョンで書式が変わった場合に備え、**解釈に失敗しても例外にはせず**
`cylinder=None` として生の文字列を `cylinder_raw` に保持します。
状態監視は 2 秒ごとに動き続けるため、1 回の解釈失敗でループを止めない作りにしています。

### `fddctl -c protect` は状態を反転させるトグル

`fddctl -i ID -c protect` は **現在の状態を反転させます**（実機で確認済み）。
`on` / `off` のような状態指定ではありません。

一方、Web UI と API は「ライトプロテクトを有効／無効にする」という指定を受け取ります。
そのため `RealFDX68Backend.set_write_protect()` では、
**現在の状態を読んでから、希望する状態と異なる場合だけ**コマンドを実行します。

これを省いて毎回実行すると、既に希望どおりの状態のときに反転してしまい、
**実機のライトプロテクトが意図と逆になります。**
この挙動は `tests/unit/test_real_backend_commands.py` で固定しています。

### `fddctl --stop` だけで fddemu は停止する

`fddctl --stop` で fddemu が確実に停止・終了することを確認済みです。
通常の停止操作で `pkill` へのフォールバックが実行されることはありません。

それでも `pkill` を残しているのは、**fddemu が IPC ソケットに応答しなくなった場合**の
ためです。`--stop` はソケット経由で要求を送るため、fddemu がハングしていると効きません。
まさにそのときに `pkill` が必要になります。

停止処理の順序は次の通りです。

```
1. fddctl --stop          正規の手順。通常はここで停止する
2. pgrep -x fddemu        残っているか確認
3. pkill -x fddemu        応答しない場合のみ
4. pkill -x -9 fddemu     それでも残る場合のみ
```

`pkill` に `-x`（完全一致）を付けているのは、`fddemu` を名前に含む別プロセスを
誤って巻き込まないためです。

### `fddctl` は root 権限を必要としない

`fddemu` は `/dev/mem` を使うため root 必須ですが、**`fddctl` は非 root で実行できます。**
fddemu が root で動作していても、非 root のまま IPC ソケットへ接続できます。

そのため以下のようにしています。

- `fddctl` は `sudo` を経由せず、そのまま実行する
- `/etc/sudoers.d/fdx68-web` に `fddctl` を**含めない**（不要な昇格をしない）
- `FDX68_USE_SUDO` の対象は `fddemu` / `pkill` / `reboot` / `poweroff` のみ

状態監視は 2 秒ごとに `fddctl -l` を実行するため、これを毎回 sudo 経由にすると
不要な昇格が常態化するうえ、プロセス起動のコストも増えます。

### 公式の推奨環境は Bookworm だが Trixie でも動作する

公式 readme には「Raspberry Pi OS (Bookworm) の 32/64 ビット版で開発およびテスト」と
ありますが、**Trixie (Debian 13) でも問題なく動作**しています（本環境で確認）。

---

## 未確定（実機で確認して、結果をここに追記する）

### ディスク挿入時の X68000 側の認識

- [ ] `fddctl -c insert` の直後に X68000 がディスク交換を認識するか
- [ ] X68000 がディスクにアクセス中に挿入・イジェクトした場合、どうなるか
- [ ] 複数枚組ソフトで、ディスク交換要求に対して Web UI からの挿入が間に合うか
