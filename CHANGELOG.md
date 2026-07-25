# 変更履歴

このファイルの形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に従い、
バージョン番号は [セマンティック バージョニング](https://semver.org/lang/ja/) に従います。

## [Unreleased]

### 追加

- 初期実装（開発中）
- Web UI から Web UI 自身のサービスを再起動できるようにした（主に開発中の再読み込み用）。
  復帰すると自動的にページを再読み込みする

### 変更

- systemd unit に `KillMode=process` を指定し、`fddemu` がサービスの停止・再起動に
  巻き込まれないようにした。これにより Web UI を再起動しても
  X68000 から見えているドライブが維持される
- `/api/health` にプロセスの起動時刻 `started_at` を追加した
- `./scripts/test.sh` に `install.sh --dry-run` を追加し、CI と同じ範囲をローカルでも確認できるようにした

### 修正

- FDX68 の対象外アーキテクチャ（x86_64 など）で `install.sh --dry-run` がエラー終了していた問題を
  修正した。dry-run では警告を出して導入手順を飛ばし、以降の分岐の確認を続ける。
  実際の導入では従来どおりエラーで中止する

### 対応する FDX68 のバージョン

- FDX68 2.10（`fdx68_210_aarch64.tar.gz` / `fdx68.tar.gz`）
