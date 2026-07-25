# CLAUDE.md

このファイルは Claude Code がセッションごとに読み込むプロジェクト指示です。
コードを読めば分かることは書きません。**読んでも分からない前提・禁止事項・運用手順**だけを書いています。

---

## このプロジェクトは何か

X68000 実機の FDD インターフェースに接続された Raspberry Pi 上の **FDX68** を、
Web ブラウザから操作するためのフロントエンドです。

```
Web Browser
    ↓ HTTP / WebSocket
FastAPI (このリポジトリ)
    ↓ subprocess
fddemu / fddctl / fdxconv / fdxtool   ← FDX68 本体（別ソフト・再配布不可）
    ↓ GPIO / FDD信号
X68000 実機
```

**ディスクイメージは代替不能な資産**です。単なるファイルとして扱わず、
壊す・消す・上書きする操作には常に慎重になってください。

---

## 開発環境と実行環境が違う（クロス開発）

| | 開発ホスト | 実行ターゲット |
|---|---|---|
| 機種 | macOS (Apple Silicon) | Raspberry Pi 3 Model A+ |
| Python | 3.14 系 | 3.13 系 |
| バックエンド | `FDX68_BACKEND=mock` | `FDX68_BACKEND=real` |

Raspberry Pi は **実装メモリ 415MB / 空き 275MB** しかありません。
メモリを大量に消費する実装（ファイル全体をメモリに載せる等）は動きません。

`requires-python = ">=3.11"` です。Raspberry Pi OS Bookworm (Python 3.11) でも
動く必要があるため、3.12 以降でしか使えない構文・API は使わないでください。

---

## 絶対に守るルール

違反すると実害が出るものだけを挙げます。

### 実機・ハードウェアに関わるもの

- **macOS 上で実機の FDX68 コマンドを実行しない。** ローカルでは必ず `FDX68_BACKEND=mock`。
- **`reboot` / `poweroff` / `fddemu` の停止を、確認なしに実行しない。**
  X68000 がディスクにアクセス中の可能性があります。
- FDX68 の仕様は **公式ドキュメントより実機の挙動を優先**します。
  食い違いを見つけたら `docs/reference/fdx68-version-notes.md` に記録してください。

### ディスクイメージに関わるもの

- **挿入中のディスクイメージを削除・リネーム・移動しない。**
  fddemu は挿入時のパスを保持しているため、動かすと参照が壊れます。
  判定には `image_service.assert_not_mounted()` を使ってください。
- **既存のディスクイメージを無断で上書きしない。**
  変換先・アップロード・複製・移動・新規作成のすべてで、既存があれば 409 で拒否します。
- **書き込みは `.part` 経由の原子的置換にする。**
  途中まで書けたディスクイメージは一見正常に見えてしまい、実機に挿入すると壊れたディスクとして扱われます。
- **拡張子を変えただけで「変換した」ことにしない。** 変換は必ず `fdxconv` を通します。

### セキュリティに関わるもの

- **`subprocess` は引数リスト形式で呼び、`shell=True` を使わない。**
- **クライアントから絶対パスを受け取らない。** パスは必ず `image_service.resolve_safe()` を通します。
- **このリポジトリは GitHub で公開されます。接続先ホスト名・IP アドレス・パスワードを書かない。**
  実機の接続情報は git 管理外の `.env.deploy` に置きます（`.gitignore` 済み）。
  コミット前に、追加した内容に接続情報が混ざっていないか確認してください。

---

## 作業手順

```bash
./scripts/test.sh      # Unit → Integration → ruff → shellcheck → dry-run
./scripts/deploy.sh    # テストが通らなければデプロイしない
./scripts/logs.sh      # 実機のサービス状態・ログ・fddctl -l をまとめて取得
```

ローカルでの動作確認:

```bash
source .venv/bin/activate
uvicorn app.main:app --reload    # http://localhost:8000
```

実機への接続は `.env.deploy` に設定します（`.env.deploy.example` を参照）。
初回のみ `ssh-copy-id` での公開鍵配置が必要です（手順は `docs/development/deployment.md`）。

---

## 変更時のチェックリスト

更新漏れが起きやすい箇所です。

| 変更内容 | 同時に更新するもの |
|---|---|
| 環境変数を追加した | `.env.example` / `app/config.py` / `scripts/install.sh` の生成ロジック / `README.md` |
| FDX68 コマンドへの依存を追加した | `scripts/install.sh` の前提条件検査 |
| API を追加した | `tests/integration/` とフロントエンド（`frontend/js/api.js`）の両方 |
| UI に要素を追加した | JS からインライン style を書かず `data-*` 属性と CSS で表現する |
| FDX68 の新版に対応した | `packaging/fdx68-source.conf` の 3 値（バージョン・URL・SHA256）と `CHANGELOG.md` |
| 実機で仕様を確認した | `docs/reference/fdx68-version-notes.md` |

---

## 文章はすべて日本語で書く

ドキュメント、コード内のコメントと docstring、Web UI の表示文言、エラーメッセージ、
`install.sh` が表示するメッセージ、`CHANGELOG.md` — すべて日本語です。

FDX68 そのものが日本語で提供されており、利用者層も日本語圏であるためです。
公開後も日本語を基本とします。

例外は機械的に決まる識別子だけです（変数名・関数名・API のフィールド名・
`data-*` 属性の値・git のブランチ名）。これらは慣例通り英語のままにします。

---

## 設計上、意図的にそうしている点

後から「なぜこうなっているのか」が分からなくなりやすい箇所です。変更する前に理由を確認してください。

- **バックエンドの切り替えはファクトリ経由**（`app/backends/factory.py`）。
  `platform.system()` による分岐をコード中に散在させないためです。
- **`fddctl` の異常は終了コードではなく出力の `Error` 文字列で判定**します。
  実測で、エラー時も終了コード 0 を返す場合があることを確認しています。
- **subprocess の入出力は `encoding="utf-8", errors="replace"` で明示的にデコード**します。
  周囲のロケール設定に依存させないため、また 1 回のデコード失敗で監視ループを止めないためです。
- **状態監視は `fddctl -l` のポーリング**で、ツリー全体のスキャンはしません。
  SD カードを頻繁に走査すると fddemu のリアルタイム動作に影響するためです。
- **`fddctl` は `sudo` を経由しません。** root 権限を必要としないことを実機で確認済みです。
  sudoers にも含めていません。`sudo` を付けるのは `fddemu`（`/dev/mem` を使うため root 必須）と
  `pkill` / `reboot` / `poweroff` だけで、これは `FDX68_USE_SUDO` の対象です。
  権限の境界は `tests/unit/test_real_backend_commands.py` で固定しています。
- **`fddctl -c protect` は状態指定ではなくトグル**です。API は「有効／無効」を受け取るので、
  現在の状態を読んでから異なる場合だけ実行します。毎回実行すると実機のプロテクトが逆になります。
- **`fddemu` の停止は `fddctl --stop` で足ります。** 後続の `pkill` は、fddemu が
  IPC ソケットに応答しなくなった異常時のフォールバックで、正常時には実行されません。
- **ライトプロテクトは 2 種類あります。** `fddctl -c protect` は fddemu の実行時状態（電源を切れば消える）、
  `fdxtool -s -p on` は FDX ファイル自体の属性（永続する）。UI でも別物として扱っています。
- **FDX と変換可能イメージのアイコンは同じ**です。どちらもフロッピーディスクイメージであり、
  違いは「そのまま使えるか」という状態なので `[要変換]` バッジで表現しています。

---

## FDX68 について

- 対象バージョン: **2.1.0**（`VERSION` ファイル上は `2.10`）
- `fddemu` は `/dev/mem` を使うため **root 権限が必須**です
- **FDX68 本体は再配布できません。** リポジトリへの同梱や GitHub Release へのミラーは禁止です。
  `install.sh` は公式サイトから直接ダウンロードします（専用シールド所有の確認を経たうえで）。
- コマンドの詳細は `docs/reference/fdx68-reference.md`、実機との差異は `docs/reference/fdx68-version-notes.md` に記録しています。
