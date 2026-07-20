# アーキテクチャ

## 全体構成

```
Browser（素の HTML / CSS / JavaScript）
    │ HTTP / WebSocket
    ▼
FastAPI（app/main.py）        ── 非 root の一般ユーザーで稼働
    │
    ▼
Service Layer                 fdx68_service / image_service / system_service
    │                         業務ロジック・検証・ガード条件
    ▼
FDX68 Backend                 base.py ─┬─ real.py   （Raspberry Pi）
    │                                  └─ mock.py   （macOS）
    ▼
CommandRunner                 SubprocessCommandRunner / FakeCommandRunner
    │
    ▼
subprocess                    引数リスト形式・shell=True 禁止・UTF-8 明示
    │
    ▼
fddemu / fddctl / fdxconv / fdxtool
```

**FastAPI のハンドラから直接 subprocess を呼びません。** 層を分けることで、
macOS 上では Mock バックエンドに差し替えて実機なしにテストできます。

---

## ディレクトリ構成

```
app/
├── main.py                FastAPI の生成、lifespan での監視タスク起動、静的ファイル配信
├── config.py              pydantic-settings による環境変数の読み込み
├── deps.py                バックエンド・サービスの依存注入
├── api/
│   ├── status.py          GET /api/health, GET /api/status
│   ├── drives.py          ドライブ操作（挿入・排出・プロテクト）
│   ├── images.py          イメージ管理（一覧・変換・作成・移動・複製・アップロード等）
│   ├── system.py          再起動・シャットダウン
│   └── ws.py              WebSocket エンドポイント
├── services/
│   ├── fdx68_service.py   ドライブ操作・fddemu 制御の業務ロジック
│   ├── image_service.py   パス検証・ファイル操作・ガード条件
│   └── system_service.py  システム操作
├── backends/
│   ├── base.py            抽象基底クラス
│   ├── real.py            実際の FDX68 コマンドを呼ぶ
│   ├── mock.py            メモリ上の状態を返す
│   └── factory.py         FDX68_BACKEND による切り替え
├── command/
│   ├── runner.py          subprocess の実行を集約
│   └── parser.py          fddctl -l / fdxtool の出力パーサー
├── models/                Pydantic モデル
└── monitoring/
    └── status_monitor.py  状態監視のバックグラウンドタスク
```

---

## 設計上の判断とその理由

### バックエンドの切り替えはファクトリで一元化する

```python
# app/backends/factory.py
def create_backend(settings: Settings) -> FDX68Backend:
    if settings.backend == "mock":
        return MockFDX68Backend(...)
    return RealFDX68Backend(...)
```

`platform.system() == "Darwin"` のような判定をコード中に散在させません。
散在すると、実機でのみ発生する不具合を macOS 上で再現できなくなり、
テストの信頼性が下がります。

### `fddctl` の成否は終了コードで判定しない

実測で、`fddemu` が停止している状態の `fddctl -l` が
`Error : Can't connect to emulator process` を出力しながら終了コード 0 を返しました。

そのため `parser.py` は**出力に `Error` が含まれるかどうか**も判定に使います。

### subprocess の入出力は UTF-8 を明示する

`encoding="utf-8", errors="replace"` を明示し、子プロセスにも
`LANG=C.UTF-8` / `PYTHONUTF8=1` を渡します。

理由は 2 つあります。周囲のロケール設定（systemd 経由か対話 SSH かで異なる）に
解釈を左右させないため。そして、想定外のバイト列が混じっても
デコード例外で状態監視ループを止めないためです。監視は 2 秒ごとに動き続けるので、
1 回の失敗でアプリ全体が停止する作りにはできません。

### 状態監視は単一のバックグラウンドタスク

`lifespan` で 1 つだけ起動し、`fddctl -l` を定期実行します。

- 直前のスナップショットと比較し、**変化があったときだけ**ブロードキャストする
- WebSocket クライアントが 0 件のときはポーリング間隔を延ばす

`fddemu` は GPIO のビットバンギングで FDD 信号を生成しており、
タイミングにシビアです。2 秒ごとの `fork`/`exec` でもジッタの要因になりうるため、
無駄なポーリングは避けます。

### イメージディレクトリの定期スキャンはしない

ディレクトリの変更検知のためにツリー全体を定期的に走査する方式は採りません。
SD カードへのアクセスが fddemu のリアルタイム動作に影響しうるうえ、
イメージが増えるほど無駄が大きくなるためです。

代わりに、手動リロード・展開時の再取得・ウィンドウ復帰時の更新・
自分の API 経由の変更の WebSocket 通知、という 4 つの手段で追随します
（詳細は [ui-guidelines.md](ui-guidelines.md)）。

### パス検証は 1 箇所に集約する

```python
def resolve_safe(rel: str) -> Path:
    if PurePosixPath(rel).is_absolute():
        raise InvalidPath
    root = settings.image_dir.resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise InvalidPath
    return target
```

`Path.resolve()` はシンボリックリンクも解決するため、
ルート外を指すシンボリックリンク経由の脱出も同時に塞げます。

新規作成・リネーム・移動では、名前の検証を通したあとに
**結合結果を再度ルート配下チェックにかけます**（多層防御）。

### 「挿入中かどうか」の判定は共通ヘルパーにする

削除・リネーム・移動・ディスク属性編集の 4 箇所で必要になるため、
`image_service.assert_not_mounted()` として 1 つだけ実装します。

ガード条件が分散すると、新しい操作を追加したときに
チェックを入れ忘れて挿入中のイメージを壊す事故につながります。

### 書き込みは `.part` 経由の原子的置換

アップロード・複製では、同一ディレクトリに `<name>.part` として書き、
完全に書き終えてから `os.replace()` で本来の名前にします。

ディスクイメージは途中まで書けたファイルが一見正常に見えてしまい、
それを実機に挿入すると壊れたディスクとして扱われます。
中途半端なファイルを `.fdx` という名前で存在させないことが重要です。

---

## 権限の分離

`fddemu` は `/dev/mem` を使うため root 権限が必須ですが、
**Web アプリ全体を root で動かすことはしません**。

```
fdx68-web.service（非 root の一般ユーザー）
    │
    ├─ sudo -n /usr/local/bin/fddemu      ← 必要な操作だけ昇格
    │  sudo -n /usr/bin/pkill -x fddemu
    │  sudo -n /sbin/reboot
    │  sudo -n /sbin/poweroff
    │  sudo -n /usr/bin/systemctl --no-block restart fdx68-web.service
    │
    └─ fddctl / fdxconv / fdxtool         ← 昇格せずそのまま実行
```

対象コマンドは `/etc/sudoers.d/fdx68-web` で列挙します（[deployment.md](deployment.md)）。

**`fddctl` は root 権限を必要としません**（実機で確認済み）。
fddemu が root で動作していても、非 root のまま IPC ソケットに接続できます。
2 秒ごとに実行される `fddctl -l` を毎回 sudo 経由にすると、
不要な昇格が常態化するうえプロセス起動のコストも増えるため、そのまま実行します。

`fdxconv` / `fdxtool` も同様に、ファイル操作のみで GPIO を触らないため昇格しません。

---

## fddemu はサービスの再起動をまたいで生き残る

unit に `KillMode=process` を指定しています。

systemd の既定（`KillMode=control-group`）では、unit を停止するときに
cgroup 内の全プロセスにシグナルが飛びます。アプリは `fddemu` を
`start_new_session=True` で起動していますが、これはセッションを分けるだけで
cgroup からは抜けないため、既定のままだと `fddemu` も一緒に落ちます。

`fddemu` は X68000 から見えているフロッピードライブそのものです。
Web UI の再起動やデプロイのたびにドライブが消えるのは受け入れられないため、
シグナルの対象を主プロセス（uvicorn）だけに限定しています。

アプリは `fddemu` を PID ではなく `pgrep -x fddemu` で発見する設計なので、
再起動後の新しいプロセスからもそのまま制御できます。

副作用として、`systemctl stop` でも `fddemu` は残ります。
止めたいときは Web UI か `fddctl --stop` を使ってください。

これにより、Web UI からの「Web UI 再起動」（`POST /api/system/restart-service`）が
X68000 に影響を与えずに済みます。この API は
`sudo -n systemctl --no-block restart fdx68-web.service` を実行します。
`--no-block` を付けるのは、完了を待つと自分自身が停止させられて
HTTP 応答を返せなくなるためです。

再起動の完了はフロントエンドが `/api/health` の `started_at`
（プロセスの起動時刻）の変化で判定し、変わったらページを再読み込みします。
「応答が落ちるのを待つ」方式では、再起動が速いと落下を観測できず取りこぼします。

---

## WebSocket のメッセージ形式

種類を後から増やせるよう、封筒形式にします。

```json
{ "type": "status", "fddemu_running": true, "drives": [ ... ] }
{ "type": "images_changed", "path": "X68000/yamikets" }
```

- `status` … ドライブ状態。変化があったときのみ送信
- `images_changed` … ファイル操作の通知。複数のタブや端末で表示が食い違わないようにする

新規接続時には現在の状態を即座に 1 回送ります。
