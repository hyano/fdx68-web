"""環境変数による設定。

設定項目を追加したら、`.env.example` と `scripts/install.sh` の生成ロジック、
`README.md` の一覧も同時に更新すること。
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """アプリケーション設定。環境変数または .env から読み込む。"""

    model_config = SettingsConfigDict(
        env_prefix="FDX68_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # mock は実際の FDX68 コマンドを呼ばない（macOS での開発用）
    backend: Literal["mock", "real"] = "mock"

    # Web UI からはこのディレクトリの配下しか見えない
    image_dir: Path = Path("/home/pi/fdximg")

    bin_dir: Path = Path("/usr/local/bin")

    # root 権限が必要なコマンド（fddemu / pkill / reboot / poweroff / systemctl）を
    # sudo -n 経由で実行するか。アプリ自体を root で動かす場合は false にする。
    #
    # fddctl はこの設定の対象外である。root 権限を必要としないことを実機で
    # 確認しており、常に非 root で実行する。
    use_sudo: bool = True

    # fddctl -l の実行間隔（秒）。短くしすぎると fddemu のリアルタイム動作に影響する。
    status_interval: float = 2.0

    max_upload_mb: int = 256

    # 空なら FDX68 の既定値（-o x1 -o q0 -o m1 -o c0）が使われる
    fddemu_options: str = ""

    # Web UI 起動時に fddemu も自動起動するか
    autostart_fddemu: bool = True

    host: str = "0.0.0.0"  # noqa: S104  LAN 内からアクセスするため全インターフェースで待ち受ける
    port: int = 8000

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def command_path(self, name: str) -> str:
        """FDX68 コマンドの絶対パスを返す。"""
        return str(self.bin_dir / name)


@lru_cache
def get_settings() -> Settings:
    """設定を返す（プロセス内でキャッシュする）。"""
    return Settings()
