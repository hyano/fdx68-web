"""FDX68 バックエンドの抽象。

実機用（real）と開発用（mock）の 2 実装がある。
どちらを使うかは factory.py で決め、OS 判定をコード中に散在させない。
"""

from abc import ABC, abstractmethod
from pathlib import Path

from app.models.drive import FDX68Status
from app.models.image import AnalyzeMode, DataFormat, DiskInfo, DiskType


class FDX68Backend(ABC):
    """FDX68 の操作。

    ここに現れるパスはすべて**絶対パス**である。
    相対パスからの変換と検証は Service 層（image_service）が済ませている前提。
    """

    # --- 状態取得 -----------------------------------------------------------

    @abstractmethod
    async def get_status(self) -> FDX68Status:
        """`fddctl -l` 相当。

        fddemu が停止している場合は例外にせず、
        `fddemu_running=False` の状態を返すこと（停止は正常な状態のため）。
        """

    @abstractmethod
    async def is_fddemu_running(self) -> bool:
        """fddemu プロセスが動作しているか。"""

    # --- fddemu の制御 ------------------------------------------------------

    @abstractmethod
    async def start_fddemu(self, options: str | None = None) -> None:
        """fddemu をバックグラウンドで起動する。

        起動後に疎通確認まで行い、失敗したら例外を送出すること。
        """

    @abstractmethod
    async def stop_fddemu(self) -> None:
        """fddemu を停止する。"""

    # --- ドライブ操作 -------------------------------------------------------

    @abstractmethod
    async def insert(self, drive_id: int, image_path: Path) -> None:
        """ドライブにディスクイメージを挿入する。"""

    @abstractmethod
    async def eject(self, drive_id: int) -> None:
        """ドライブからディスクイメージをイジェクトする。"""

    @abstractmethod
    async def set_write_protect(self, drive_id: int, enabled: bool) -> None:
        """ライトプロテクト（fddemu の実行時状態）を設定する。

        FDX ファイル自体の属性を変える `fdxtool -s` とは別物なので混同しないこと。
        """

    # --- ディスクイメージの操作 ---------------------------------------------

    @abstractmethod
    async def convert_to_fdx(
        self,
        source: Path,
        destination: Path,
        *,
        disk_no: int = 1,
        data_format: DataFormat = DataFormat.ENCODE,
        analyze: AnalyzeMode = AnalyzeMode.UPD765,
    ) -> None:
        """`fdxconv` で FDX 形式に変換する。

        元ファイルは変更しない。変換先が既に存在する場合、
        呼び出し側が事前に拒否している前提。
        """

    @abstractmethod
    async def create_blank_image(
        self,
        destination: Path,
        *,
        disk_type: DiskType = DiskType.TWO_HD,
        disk_name: str | None = None,
        write_protected: bool = False,
        data_format: DataFormat = DataFormat.ENCODE,
    ) -> None:
        """`fdxtool -c` でブランクの FDX を作成する。

        生成されるのは**未フォーマットのディスク**であり、
        使用前に X68000 側で FORMAT.X によるフォーマットが必要。
        """

    @abstractmethod
    async def get_disk_info(self, path: Path) -> DiskInfo:
        """`fdxtool FILE` でディスク情報を取得する。"""

    @abstractmethod
    async def set_disk_attributes(
        self,
        path: Path,
        *,
        disk_name: str | None = None,
        write_protected: bool | None = None,
    ) -> None:
        """`fdxtool -s` で FDX ファイル自体のディスク名・WP 属性を変更する。"""

    # --- システム操作 -------------------------------------------------------

    @abstractmethod
    async def reboot(self) -> None:
        """Raspberry Pi を再起動する。"""

    @abstractmethod
    async def poweroff(self) -> None:
        """Raspberry Pi をシャットダウンする。"""

    @abstractmethod
    async def restart_service(self) -> None:
        """Web UI 自身のサービスを再起動する。主に開発中の再読み込み用。"""
