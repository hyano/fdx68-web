# ドキュメント索引

FDX68 Web Controller のドキュメントを読者別にまとめています。
プロジェクト全体の概要は [../README.md](../README.md)、開発時の前提・禁止事項・運用手順は
[../CLAUDE.md](../CLAUDE.md) を参照してください。

---

## guide/ — 利用者・導入担当者向け

| ドキュメント | 内容 |
|---|---|
| [guide/installation.md](guide/installation.md) | 素の Raspberry Pi OS への導入・アップデート・アンインストール・トラブルシューティング |

## development/ — 開発者向け

| ドキュメント | 内容 |
|---|---|
| [development/architecture.md](development/architecture.md) | 全体構成・ディレクトリ構成・設計上の判断とその理由 |
| [development/development-environment.md](development/development-environment.md) | macOS ↔ Raspberry Pi のクロス開発環境とセットアップ |
| [development/deployment.md](development/deployment.md) | 開発中の rsync デプロイ・systemd・sudoers・ログ確認 |
| [development/testing.md](development/testing.md) | テストの 3 段階（Unit / Integration / Hardware）と CI の方針 |
| [development/hardware-integration.md](development/hardware-integration.md) | Raspberry Pi + X68000 実機を使う手動チェックリスト |
| [development/ui-guidelines.md](development/ui-guidelines.md) | ビルド工程を持たないフロントエンドの実装方針 |

## reference/ — 参照資料

| ドキュメント | 内容 |
|---|---|
| [reference/requirements.md](reference/requirements.md) | 背景・目的・機能要件・非機能要件 |
| [reference/fdx68-reference.md](reference/fdx68-reference.md) | FDX68 コマンドリファレンス（公式仕様＋実測） |
| [reference/fdx68-version-notes.md](reference/fdx68-version-notes.md) | 公式ドキュメントと実機の差異の実測メモ（実装判断はこちらを優先） |
