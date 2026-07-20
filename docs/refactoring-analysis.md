# リファクタリング分析

プロジェクト全体（`app/` 4 層 + `frontend/` + `tests/` + `docs/` + `scripts/`）を調査した結果を記録する。

調査時点: 2026-07-21 / ブランチ `fix-node-action-visibility` / テスト 136 件すべて成功

---

## 総評

**このコードベースは既に良好な状態にある。** 大規模な作り直しは不要であり、するべきでもない。

- 層構造（API → Service → Backend → CommandRunner → subprocess）は明確に分離されており、
  `docs/architecture.md` の記述とも概ね一致している
- パス検証は `services/paths.py` に集約され、攻撃的な入力に対するテストも厚い
- 「なぜそうなっているか」のコメントが要所に残されており、意図が追える
- Mock / Real の切り替えはファクトリに閉じている
- インラインスタイルの禁止（CLAUDE.md のルール）は**違反ゼロ**

したがって本分析は、**局所的な不整合の解消**に絞る。以下、深刻度順ではなく分類ごとに列挙し、
最後にリスク順の実行計画を示す。

---

## 1. 型安全性

### 1-1. `save_upload` の二重インタフェースと型の抜け穴 【重要】

`app/services/image_service.py:481-599`

```python
async def save_upload(self, dest_dir, filename,
                      chunks: Iterable[bytes] | None = None,
                      *, reader: object | None = None) -> str:
...
async def _iter_chunks(chunks, reader):  # noqa: ANN202
    ...
    read = reader.read  # type: ignore[attr-defined]
```

`chunks` 引数は**アプリケーションからもテストからも一度も使われていない**（唯一の呼び出しは
`app/api/images.py:212` の `reader=upload_file`）。使われない分岐を維持するために、
`reader: object | None` という実質 `Any` の型と `# type: ignore` と `# noqa: ANN202` の
3 つの抜け穴が生まれている。

→ `chunks` を削除し、`read(size) -> bytes` を持つ `Protocol` を定義すれば
抜け穴 3 つがすべて消え、関数も短くなる。

### 1-2. WebSocket の依存注入が型を偽っている

`app/api/ws.py:23-24`

```python
manager = get_connection_manager(websocket)  # type: ignore[arg-type]
monitor = get_status_monitor(websocket)      # type: ignore[arg-type]
```

`app/deps.py` の各 getter は `Request` を受ける宣言だが、実際に渡しているのは `WebSocket`。
両者の共通基底は Starlette の `HTTPConnection` であり、そちらで受ければ嘘がなくなる。

→ `deps.py` の引数型を `HTTPConnection` にすると `type: ignore` 2 つが消える。
実行時の挙動は変わらない（どちらも `.app.state` を読むだけ）。

### 1-3. レスポンスモデルのない endpoint

`app/api/images.py` の 6 endpoint（`mkdir` / `create` / `convert` / `duplicate` /
`rename` / `attributes`）と `app/api/system.py` の 3 endpoint が、
`response_model` なしの `dict[str, str]` を返している。
同じファイル内の `list` / `info` / `upload` / `move` / `delete` は `response_model` 付き。

→ `PathResponse` / `MessageResponse` の 2 モデルを導入すれば統一でき、
OpenAPI スキーマにも型が出る。レスポンス本体の JSON は変わらない。

### 1-4. `ConnectionManager` の `Any`

`app/monitoring/status_monitor.py:29,36,41,46` — `set[Any]` / `websocket: Any`。

→ `send_json` だけを要求する小さな `Protocol` にすると、
`monitoring` が FastAPI に依存しないまま型が付く。

---

## 2. エラー処理の統一

### 2-1. 同じ条件が別の例外・別のステータスになっている 【重要】

「FDX 形式ではないファイル」に対する扱いが 2 通りある。

| 場所 | 例外 | HTTP |
|---|---|---|
| `app/services/fdx68_service.py:81-84`（挿入） | `CommandFailed` | **500** |
| `app/services/image_service.py:325`（情報取得） | `UnsupportedFileType` | 400 |
| `app/services/image_service.py:343`（属性変更） | `UnsupportedFileType` | 400 |

挿入時だけ、利用者の入力ミスがサーバーエラー（500）として返る。
`tests/integration/test_api_basics.py:60` がこの 500 を固定してしまっている。

→ `UnsupportedFileType`（400）に統一するのが正しい。**ただし API の契約変更**なので要判断。

### 2-2. ドライブ番号の検証に `InvalidPath` を使っている

`app/services/fdx68_service.py:66-68` — ドライブ番号はパスではない。
例外名と実態が食い違っており、読み手を誤らせる。
（なお API 層の `ge=0, le=1` により通常は 422 で弾かれるため、これは多層防御側の検査。）

### 2-3. Mock と Real で例外の種類が違う

`app/backends/mock.py:97-106` は fddemu 停止・ドライブ不在をすべて `CommandFailed`（500）で返すが、
`app/backends/real.py` 側では `FddemuNotRunning`（409）が使われる。
Mock で通ったテストが実機で別のステータスになりうる。

---

## 3. 重複コード

### 3-1. 一括操作ループが 3 箇所に重複 【重要】

`app/api/images.py` の `upload`(209-223) / `move`(240-251) / `delete`(308-318) は、
「1 件ずつ処理 → `FDX68Error` を捕まえて `OperationResult` に詰める → 成功があれば通知」
という同一構造を 3 回書いている。

→ 共通ヘルパー 1 つに集約できる。新しい一括操作を足すときの取りこぼしも防げる。

### 3-2. `str(FilePath(path).parent)` が 5 箇所、しかも値が不整合 【重要】

`app/api/images.py:184, 260, 273, 290, 312`

ルート直下のファイル（例 `disk1.fdx`）では `str(Path("disk1.fdx").parent)` が **`"."`** になる。
一方 `ImageListing.path` はルートを **`""`** で表す。同じ「ルートの相対パス」に 2 つの表現がある。

現状は `frontend/js/tree.js:231` の `path === "." ? ROOT_PATH : path` で辻褄を合わせているが、
これはフロントエンドがバックエンドの都合を吸収している状態であり、責務が逆。

→ `""` を返す `parent_of()` ヘルパーに統一し、フロント側の正規化は互換のため残す。

### 3-3. `image_service` のガード前置きが 7 箇所で重複

`resolve()` → `exists()` チェック → `NotFound` の 3 行が
`convert` / `get_info` / `set_attributes` / `rename` / `move` / `duplicate` / `delete` に散在。
加えて `target == self.root.resolve()` が 3 箇所、
`classify(...) is not ImageKind.FDX` → `UnsupportedFileType` が 2 箇所。

→ `_require_existing()` / `_require_fdx()` / `_reject_root()` の私有ヘルパーに寄せる。
**ガード条件そのものは緩めない**（CLAUDE.md の禁止事項）。

### 3-4. フロントエンドの重複

- 失敗一覧の生成が 2 箇所で同一（`app.js:521-523` と `app.js:719-721`）
- 「親を再取得して選択解除」が 3 箇所（`app.js:425-426, 530-532, 729-732`）
- 「アクセス中なら確認ダイアログ」が 2 箇所（`app.js:388-397` の挿入と `459-468` の複製）

### 3-5. 局所 import が 2 箇所

- `app/api/status.py:35` — ハンドラ内で `from app.config import get_settings`。
  `SettingsDep` があるのに使っていない。さらに同ハンドラの引数 `service: FDX68ServiceDep` は**未使用**。
- `app/backends/mock.py:179` — メソッド内で `from app.command.parser import parse_disk_info`。
  循環 import はないので先頭に移せる。

---

## 4. 責務分離 / FDX68 固有処理の分離

### 4-1. `download` ハンドラにサービス層のロジックがある

`app/api/images.py:110-133` — `resolve()` / `exists()` / `is_dir()` の判定が API 層にある。
他の endpoint はすべてサービスに委譲しているので、ここだけ層を跨いでいる。

→ `ImageService.resolve_for_download()` に移す。

### 4-2. Mock が FDX68 の出力形式に依存している 【設計上の要点】

`app/backends/mock.py:149-208`

Mock は `create_blank_image` で **`fdxtool` の出力を模したテキスト**をファイルに書き、
`get_disk_info` でそれを**本物の `parse_disk_info` で読み戻し**、
`set_disk_attributes` では**そのテキストを行単位で書き換えて**いる。

つまり Mock が FDX68 の出力書式という実機固有の知識に縛られている。
FDX68 の書式が変われば Mock も壊れ、`tests/integration/conftest.py:26` の
フィクスチャ（`b"FDX68-MOCK-IMAGE\nDisk Name : DISK1\n"`）も道連れになる。

これが本プロジェクトで **Mock / Real の差異が最も不適切に混ざっている箇所**である。

→ Mock はディスク属性をメモリ上の `DiskInfo` として保持し、
`parse_disk_info` に依存しない形にするのが筋。ただしテストフィクスチャに波及するため中リスク。

### 4-3. 適切に分離できている点（変更しない）

- `_friendly_message`（`real.py:319-330`）の FDX68 エラー文言の和訳 — Real 固有の知識が Real にある。正しい。
- `parser.py` の書式知識 — `command/` 層に閉じている。正しい。
- `fddctl -c protect` のトグル吸収（`real.py:202-217`）— 実機の癖を Backend が吸収している。正しい。

---

## 5. 過剰な実装・死んだコード

| 箇所 | 内容 |
|---|---|
| `frontend/js/tree.js:55-58` | `onAction` / `onError` を受け取り保存するが**一度も読まれない**（`app.js:48` は `{}` を渡す） |
| `frontend/js/tree.js:62, 267` | `this.mounted` は書かれるだけで読まれない |
| `app/services/paths.py:92-97` | `startswith(".") and endswith(".")` の分岐は、直後の `endswith(".")` に完全に包含される死に枝 |
| `app/services/image_service.py:485` | `chunks` 引数（→ 1-1） |
| `frontend/js/app.js:676` | `!external && alt ? "copy" : external ? "copy" : "move"` は `external \|\| alt ? "copy" : "move"` と等価 |
| `app/services/paths.py:71-72` | `if name is None` は `name: str` と矛盾（型上は到達不能） |

---

## 6. テスト容易性

良好な点: `FakeCommandRunner` による Real バックエンドのコマンド検証（`test_real_backend_commands.py`）は、
権限境界を固定する仕組みとして非常に有効。`create_app(settings)` で設定を差し替えられる点も良い。

課題:

- **フロントエンドにテストが存在しない。** `app.js` は import 時に `addEventListener` を実行する
  副作用の塊で、単体テストできる形になっていない。テストランナーの導入は影響が大きいため今回は対象外とし、残件とする。
- `app/api/status.py:19` の `_STARTED_AT` はモジュールレベルの定数。再起動検知の意図的な設計なので変更しない。

---

## 7. 実装とドキュメントの不一致

`docs/architecture.md` に 4 点の乖離がある。

| 行 | 記述 | 実際 |
|---|---|---|
| 70-74 | `MockFDX68Backend(...)` と引数付きで例示 | `MockFDX68Backend()` は引数を取らない |
| 120-129 | `resolve_safe(rel: str)` が内部で `settings.image_dir` を読む例示 | 実際は `resolve_safe(root: Path, relative: str \| None)` |
| 45-48 | `services/` の一覧に `paths.py` がない | 存在する（パス検証の中核） |
| 35-59 | ディレクトリ図に `app/errors.py` がない | 存在する |

環境変数は `config.py` / `.env.example` / `README.md` の 3 者で**完全に一致**しており、問題なし。

---

## 8. 実行計画（リスクの低い順）

各フェーズの後に `./scripts/test.sh`（136 件）を実行して回帰がないことを確認する。

### フェーズ 1 — 振る舞い不変・ほぼ無リスク

1. 死んだコードの削除（5 章の 6 件）
2. 局所 import をモジュール先頭へ、`health` の未使用引数を削除（3-5）
3. `docs/architecture.md` の 4 点を実装に合わせる（7 章）

### フェーズ 2 — 内部整理・外部から観測できる振る舞いは不変

4. `save_upload` の `chunks` 削除と `ChunkReader` Protocol 導入（1-1）
5. `deps.py` を `HTTPConnection` 受けにして `type: ignore` 2 つを除去（1-2）
6. `ConnectionManager` に `Protocol` を導入（1-4）
7. `image_service` のガード前置きを私有ヘルパーへ集約（3-3）
8. `download` のロジックをサービス層へ移動（4-1）
9. フロントエンドの重複 3 種を集約（3-4）

### フェーズ 3 — API 表面に触れる（レスポンス本体は不変）

10. `PathResponse` / `MessageResponse` の導入（1-3）
11. 一括操作ループの共通化（3-1）
12. `parent_of()` 導入と `"."` → `""` の統一（3-2）

### フェーズ 4 — 振る舞いが変わる。実施前に判断が必要

13. 非 FDX の挿入を 500 → 400 に（2-1）※テスト 1 件の修正を伴う
14. ドライブ番号検証の例外を適切な型に（2-2）
15. Mock の例外種別を Real に揃える（2-3）
16. Mock を FDX68 の出力書式から切り離す（4-2）※テストフィクスチャに波及

### 対象外とするもの（過剰なリファクタリングを避けるため）

- WebSocket メッセージの型付きモデル化 — 封筒形式の柔軟性を失う割に得るものが少ない
- フロントエンドのテストランナー導入 — 影響範囲が大きく、別課題とすべき
- `_STARTED_AT` の注入化 — 意図的な設計
- `save_upload` への空き容量検査の追加 — 振る舞いの変更であり、別途検討すべき（残件）

---

## 9. 実施結果

フェーズ 1 〜 4 をすべて実施した。テストは 136 件 → **148 件**（すべて成功）。

| フェーズ | コミット | 内容 |
|---|---|---|
| 1 | `a705162` | 死んだコードの削除、局所 import の解消、ドキュメントの修正 |
| 2 | `9b374e3` | 型の抜け穴の除去、ガード条件と重複コードの集約 |
| 3 | `d5e2a07` | レスポンス型・一括操作・ルートパス表現の統一 |
| 4 | （本コミット） | エラー種別の統一、Mock の FDX68 依存の解消 |

### 振る舞いが変わった点

1. **非 FDX ファイルの挿入が 500 → 400 になった。**
   利用者の選択ミスをサーバーエラーとして返していたのを修正した。
   メッセージ本文は変えていないため、UI の表示は変わらない。

2. **`images_changed` 通知の `path` が、ルート直下では `"."` → `""` になった。**
   フロントエンドは以前から両方を受け付けるため、表示に影響はない。

3. **Mock の例外種別が Real と揃った。**
   fddemu 停止中の操作が 500 → 409、ファイル不在が 500 → 404 になる。
   これは mock だけの挙動であり、実機の応答は元から 409 / 404 だった。

4. **Mock が扱うファイルの中身が独自の JSON 形式になった。**
   開発用に手元で作った古い形式の `.fdx` は、ディスク名などが表示されなくなる
   （生の内容は従来どおり表示される）。実機には影響しない。

### 残件

- **フロントエンドにテストがない。** `app.js` は import 時に `addEventListener` を
  実行する副作用の塊で、単体テストできる形になっていない。
  テストランナーの導入を含め、別課題として扱う。
- **`save_upload` に空き容量の検査がない。** 複製（`_copy`）には `_check_space` があるが
  アップロードにはなく、SD カードを埋め尽くしうる。
  ただし Content-Length を信用してよいかの判断が必要なため、別途検討する。
- `check_command_error` は `_find_error_line` の別名になっている。
  公開 API としての意味はあるが、整理の余地は残る。
