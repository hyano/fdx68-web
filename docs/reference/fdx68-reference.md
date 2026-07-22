# FDX68 コマンドリファレンス

対象バージョン: **FDX68 2.1.0**（`VERSION` ファイル上は `2.10`、Build Jun 5 2026）

このドキュメントは、公式サイトの仕様と実機での実測結果をまとめたものです。
公式サイトと実機の挙動が食い違う場合は **実機を優先**し、差異は
[fdx68-version-notes.md](fdx68-version-notes.md) に記録します。

> 出典: http://retropc.net/gimons/fdx68/command.html

---

## FDX68 とは

X68000 などのレトロ PC の FDD インターフェースに接続し、
フロッピーディスクドライブとフロッピーディスクをエミュレーションするシステムです。
Raspberry Pi に専用シールド（変換基板）を装着して使います。

```
X68000
    ↓ FDD 信号（34ピン）
専用シールド（5V ↔ 3.3V のレベル変換）
    ↓ GPIO
Raspberry Pi / fddemu
    ↓
FDX イメージファイル
```

HxC や GOTEK と同種のものですが、**X68000 のイジェクト機能やディスク挿入検知といった
拡張機能をサポートしている**点が特徴です。また KryoFlux のように実 FDD からの
ダンプ・リストアを行うコントローラ機能も持ちます。

動作モードは 2 つあります。

- **FDD エミュレーションモード** … `fddemu` / `fddctl`（本プロジェクトが使うのはこちら）
- **FDD コントローラモード** … `fdinfo` / `fdunformat` / `fddump` / `fdrestore`（実 FDD が必要）

---

## FDD エミュレーションモード

### fddemu — FDD エミュレータ本体（root 権限必須）

```
fddemu [-0 FILE] [-1 FILE] [-s OP] [-v] [-o OPTION]

 -0 FILE   1台目のドライブにディスクを挿入する。FILE は FDX ファイルのパス
 -1 FILE   2台目のドライブにディスクを挿入する
 -s OP     STEP SIGNAL の動作を選択。OP は {half|1|2}。既定は 1
 -v        verbose モード
 -h        ヘルプを表示
 -o OPTION オプション設定
```

`OPTION` は `[x0|x1|q0|q1|m0|m1|c0|c1|vn]`:

| 記号 | 意味 |
|---|---|
| `x` | X68000 拡張機能の有効/無効（`0`:off / `1`:on） |
| `q` | PC-9801 制御の有効/無効 |
| `m` | モーター信号による制御の有効/無効 |
| `c` | RAW データ補正の有効/無効 |

既定は `-o x1 -o q0 -o m1 -o c0` です。**X68000 で使う場合はディスクイメージ以外の
指定は不要**です。PC-9801 では `-o q1`（このとき X68000 拡張機能は自動的に無効になる）、
その他の機種では `-o x0` を指定します。

`-s OP` はステップ動作の調整です。PC 側から 2 回のステップ指示で 1 回分シークするのが
`half`、1 回の指示で 2 回分シークするのが `2` です。FDD 側にシーク幅を制御する機構が
ない機種で調整が必要になることがあります。

**バックグラウンドで起動することを想定**しています。

### fddctl — FDD エミュレータ制御

```
fddctl -i ID -c CMD [FILE]

 ID   ユニット番号 {0|1}
 CMD  操作コマンド {insert|eject|protect}
 FILE イメージファイルのパス

fddctl -l        デバイスリストを表示

fddctl --stop    fddemu プロセスを停止
```

バックグラウンドで動作している `fddemu` に対して、ソケット経由で
ディスクの挿入・イジェクト・ライトプロテクトの設定を行います。

`fddctl -l` の出力形式:

```
----+----+----+-------------------------------------------------
 ID | WP | CL | DISK IMAGE
----+----+----+-------------------------------------------------
  0 | ON | 00 | /home/fdx68/fdximg/X68000/yamikets/yamiketsu1.fdx
  1 | -- | 00 | EMPTY
----+----+----+-------------------------------------------------
```

- `WP` … `ON` はライトプロテクト有効、`--` は無効
- `CL` … 現在のシリンダ位置
- `DISK IMAGE` … 挿入中のイメージのパス。未挿入なら `EMPTY`

`fddemu` が起動していない場合の出力:

```
Error : Can't connect to emulator process
```

---

## ディスクイメージ変換

### fdxconv — ディスクイメージ変換

```
fdxconv -i SRCFILE [-n DISKNO] -o DESTFILE [-f FORMAT] [-a ANALYZE]

 SRCFILE   変換元イメージファイルのパス
 DISKNO    マルチイメージ形式でのディスク番号。既定は 1
 DESTFILE  変換先イメージファイルのパス
 FORMAT    DESTFILE が FDX のときのデータ形式 {encode|raw}。既定は encode
 ANALYZE   エンコードデータの解析モード {upd765|mb8877}。既定は upd765
```

**イメージの形式は拡張子から判断されます。**

FDX と相互変換可能な拡張子:

```
XDF  2HD  HDM  IMG  DUP  2HC  2HQ  2DD  DIM  D88(D68/D77)  FDI  FDD  NFD
```

- **FDX 以外から FDX への変換はすべて成功するはず**とされています
- 逆方向（FDX から他形式）には制約があります（2DD の FDX を 2HD 専用の XDF や DIM には
  変換できない等）。D88 系や NFD 形式は自由度が高く、ほぼ成功します
- `SRCFILE` と `DESTFILE` の両方に FDX 以外を指定することも可能で、
  内部で FDX を中継して相互変換されます
- `ANALYZE` は、X68000 や NEC 系では `upd765`、FM 系・X1 系では `mb8877` を使います。
  **X68000 用途では既定の `upd765` のままで正しい**

> `-n DISKNO` の既定値は **1** です（0 ではありません）。

---

## FDX ファイルユーティリティ

### fdxtool — FDX ファイル操作

**ディスク情報の表示**

```
fdxtool FILE
```

**新規ディスクの生成**

```
fdxtool -c -t TYPE [-r RPM] [-n NAME] [-p PROTECT] [-f FORMAT] FILE

 TYPE     {2D|2DD|2HD}
 RPM      {300|360}。既定は 2D/2DD が 300、2HD が 360
 NAME     ディスク名。既定は 'BLANK IMAGE'
 PROTECT  {on|off}。既定は off
 FORMAT   データ形式 {encode|raw}。既定は encode
```

**生成されるのは未フォーマットのブランクディスクです。**
セクタが存在しないため、使用前に X68000 側で `FORMAT.X` によるフォーマットが必要です。

X68000 で使う 5.25 インチ 2HD は 360rpm なので、`-t 2HD` を指定すれば
RPM は既定値で正しくなります。

**ディスク情報の設定**

```
fdxtool -s [-n NAME] [-p PROTECT] FILE
```

ディスク名とライトプロテクト属性を変更します。
**これは FDX ファイル自体の属性**であり、`fddctl -c protect` による
fddemu の実行時プロテクトとは別物です（前者は永続、後者は fddemu を止めれば消えます）。

### fdxview — ディスクイメージビューア

```
fdxview [OPTION]... FILE

 -v MODE     {track|sector|data}。既定は track
 -t TRACK    トラック番号（シリンダとヘッドを自動設定）。既定は 0
 -c CYLINDER シリンダ。既定は 0
 -h HEAD     ヘッド。既定は 0
 -s SECTOR   data モードでのセクタ番号（1 以上）。既定は 1
 -n DISKNO   マルチイメージ形式でのディスク番号。既定は 1
 -a ANALYZE  解析モード {upd765|mb8877}。既定は upd765
```

トラック一覧、セクタ一覧、セクタデータを表示します。
変換や複製が正しく行われたかの確認に使えます。

### fdxtrkcpy — トラック情報コピー

```
fdxtrkcpy -i SRCFILE -o DESTFILE [-t TRACK] [-c CYLINDER] [-h HEAD]
```

FDX の特定トラックを別の FDX にコピーします。
破損したトラックを別の FDX のデータで補完・修復する用途を想定しています。

---

## FDD コントローラモード（実 FDD が必要・本プロジェクトでは未使用）

いずれも **root 権限が必要**です。

### fddump — 実ディスクからのダンプ

```
fddump -i ID [OPTION]... FILE

 -c CYLINDERS  シリンダ数。既定は 40
 -h HEADS      ヘッド数。既定は 2
 -d DENSITY    FDD の密度 {double|high}。既定は double
 -b BEGIN      開始シリンダ。既定は 0
 -e END        終了シリンダ。既定は CYLINDERS - 1
 -t TRACK      指定トラックのみ操作（-b / -e は無視される）
 -s STEPS      シークのステップ数 {1|2}。既定は 1
 -n LEVEL      ノイズ除去レベル。既定は 8
 -a ANALYZE    解析モード {upd765|mb8877}。既定は upd765
 -f FORMAT     データ形式 {encode|raw}。既定は encode
 -p2 / -p4 / -p12   ピン 2 / 4 / 12 をアサート
 -r RETRY      不正トラックのリトライ回数。既定は 5
 -v            verbose モード
```

開始・終了シリンダを指定したときに既存のイメージファイルが存在する場合は、
そのイメージのシリンダ数・ヘッド数・密度・RAW 指定が優先されます
（＝特定シリンダのみ再ダンプして上書きする動作になります）。

### fdrestore — 実ディスクへのリストア

```
fdrestore -i ID [OPTION]... FILE
```

オプションは `fddump` とほぼ共通で、`-n DISKNO`（マルチイメージのディスク番号）が加わります。

### fdunformat — アンフォーマット

```
fdunformat -i ID -c CYLINDERS [-h HEADS] [OPTION]...
```

### fdinfo — ドライブ情報の計測

```
fdinfo -i ID [OPTION]...
```

物理ドライブの回転数や最大シリンダを計測します。
**オーバートラック領域にヘッドをシークさせるため、最悪の場合ドライブが壊れます。**

---

## 実測した環境情報

| 項目 | 値 |
|---|---|
| バージョン | 2.1.0（`VERSION` ファイルは `2.10`）/ Build Jun 5 2026 |
| 配置先 | `/usr/local/bin` |
| パーミッション | `rwxr-xr-x`（setuid なし） |
| 同梱ファイル | コマンド 10 個 + `fddseek.wav` / `fddinsert.wav` / `fddeject.wav` |

wav ファイルは V2PRO 基板・PRO 化アドオンボードでのシーク音・挿入音・イジェクト音の
再生に使われます。これらの基板がない環境では使われません。

`fddemu` のバイナリには `/dev/mem` と `GPIOCTL::MapGpioMem` のシンボルがあり、
GPIO を直接マップするため root 権限が必要です。
`fddctl` には `socket` / `monsocket` のシンボルがあり、ソケット IPC で fddemu と通信します。

---

## 配布物

| ファイル | 対象 |
|---|---|
| `fdx68.tar.gz` | Bookworm **32bit**（armhf）。固定 URL |
| `fdx68_210_aarch64.tar.gz` | Bookworm **64bit**（aarch64）。バージョン番号付き URL のみ |
| `fdx68_210_bullseye.tar.gz` | Bullseye 32bit |
| `fdx68_210_win.zip` | Windows 用ツール群 |
| `fdx68_210_bm.zip` | fddemu のベアメタル版 |

**64bit 版に固定 URL は存在しません。** 詳細と、それを踏まえたインストーラの設計は
[installation.md](../guide/installation.md) を参照してください。
