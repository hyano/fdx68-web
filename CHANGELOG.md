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

### 対応する FDX68 のバージョン

- FDX68 2.10（`fdx68_210_aarch64.tar.gz` / `fdx68.tar.gz`）
