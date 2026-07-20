"""開発・テスト用バックエンド。

実際の FDX68 コマンドを呼ばず、メモリ上の状態を操作する。
macOS 上での開発と、CI での Integration Test に使う。

ファイルを実際に作る操作（変換・ブランク作成）については、
後続の処理が「ファイルが存在すること」を前提にするため、
中身は簡易的なものでも実際にファイルを作成する。
"""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.backends.base import FDX68Backend
from app.command.parser import parse_disk_info
from app.errors import CommandFailed
from app.models.drive import Drive, FDX68Status
from app.models.image import AnalyzeMode, DataFormat, DiskInfo, DiskType

logger = logging.getLogger(__name__)

#: mock が生成する FDX の中身（実際の FDX68 形式ではない）
_MOCK_FDX_HEADER = b"FDX68-MOCK-IMAGE\n"


@dataclass
class _MockDrive:
    """mock が保持するドライブの状態。"""

    id: int
    image: Path | None = None
    write_protected: bool = False
    cylinder: int = 0


@dataclass
class MockFDX68Backend(FDX68Backend):
    """メモリ上の状態を操作するバックエンド。"""

    fddemu_running: bool = False
    drives: dict[int, _MockDrive] = field(
        default_factory=lambda: {0: _MockDrive(id=0), 1: _MockDrive(id=1)}
    )
    #: 呼ばれた操作の履歴（テストでの検証用）
    calls: list[str] = field(default_factory=list)
    #: システム操作を実際には行わず記録だけする
    reboot_requested: bool = False
    poweroff_requested: bool = False
    service_restart_requested: bool = False

    # --- 状態取得 -----------------------------------------------------------

    async def get_status(self) -> FDX68Status:
        if not self.fddemu_running:
            return FDX68Status(
                fddemu_running=False,
                drives=[],
                message="fddemu が起動していません。",
            )

        drives = [
            Drive(
                id=d.id,
                inserted=d.image is not None,
                write_protected=d.write_protected,
                cylinder=d.cylinder,
                cylinder_raw=f"{d.cylinder:02d}",
                image=str(d.image) if d.image else None,
            )
            for d in sorted(self.drives.values(), key=lambda x: x.id)
        ]
        return FDX68Status(fddemu_running=True, drives=drives)

    async def is_fddemu_running(self) -> bool:
        return self.fddemu_running

    # --- fddemu の制御 ------------------------------------------------------

    async def start_fddemu(self, options: str | None = None) -> None:
        self.calls.append(f"start_fddemu({options})")
        if self.fddemu_running:
            raise CommandFailed("fddemu は既に起動しています。")
        self.fddemu_running = True

    async def stop_fddemu(self) -> None:
        self.calls.append("stop_fddemu")
        self.fddemu_running = False
        # 実機では fddemu を止めても挿入状態は保持されないため、状態をリセットする
        for drive in self.drives.values():
            drive.image = None
            drive.write_protected = False
            drive.cylinder = 0

    # --- ドライブ操作 -------------------------------------------------------

    def _require_running(self) -> None:
        if not self.fddemu_running:
            raise CommandFailed("fddemu が起動していません。")

    def _require_drive(self, drive_id: int) -> _MockDrive:
        self._require_running()
        drive = self.drives.get(drive_id)
        if drive is None:
            raise CommandFailed(f"ドライブ {drive_id} は存在しません。")
        return drive

    async def insert(self, drive_id: int, image_path: Path) -> None:
        self.calls.append(f"insert({drive_id}, {image_path})")
        drive = self._require_drive(drive_id)
        if not image_path.exists():
            raise CommandFailed("指定されたファイルを開けませんでした。")
        drive.image = image_path
        drive.cylinder = 0

    async def eject(self, drive_id: int) -> None:
        self.calls.append(f"eject({drive_id})")
        drive = self._require_drive(drive_id)
        drive.image = None
        drive.write_protected = False

    async def set_write_protect(self, drive_id: int, enabled: bool) -> None:
        self.calls.append(f"set_write_protect({drive_id}, {enabled})")
        drive = self._require_drive(drive_id)
        drive.write_protected = enabled

    # --- ディスクイメージの操作 ---------------------------------------------

    async def convert_to_fdx(
        self,
        source: Path,
        destination: Path,
        *,
        disk_no: int = 1,
        data_format: DataFormat = DataFormat.ENCODE,
        analyze: AnalyzeMode = AnalyzeMode.UPD765,
    ) -> None:
        self.calls.append(f"convert_to_fdx({source} -> {destination})")
        if not source.exists():
            raise CommandFailed("変換元のファイルが存在しません。")

        # 実際の変換は行わないが、後続処理のためにファイルは作る。
        # 元ファイルを変更しないことは実機と同じ。
        await asyncio.to_thread(
            destination.write_bytes,
            _MOCK_FDX_HEADER + f"converted from {source.name}\n".encode(),
        )

    async def create_blank_image(
        self,
        destination: Path,
        *,
        disk_type: DiskType = DiskType.TWO_HD,
        disk_name: str | None = None,
        write_protected: bool = False,
        data_format: DataFormat = DataFormat.ENCODE,
    ) -> None:
        self.calls.append(f"create_blank_image({destination}, {disk_type.value})")
        name = disk_name or "BLANK IMAGE"
        rpm = 360 if disk_type is DiskType.TWO_HD else 300
        content = (
            _MOCK_FDX_HEADER
            + f"Disk Name : {name}\n".encode()
            + f"Disk Type : {disk_type.value}\n".encode()
            + f"RPM : {rpm}\n".encode()
            + f"Format : {data_format.value}\n".encode()
            + f"Protect : {'on' if write_protected else 'off'}\n".encode()
        )
        await asyncio.to_thread(destination.write_bytes, content)

    async def get_disk_info(self, path: Path) -> DiskInfo:
        self.calls.append(f"get_disk_info({path})")
        if not path.exists():
            raise CommandFailed("ファイルが存在しません。")

        raw = await asyncio.to_thread(path.read_bytes)
        text = raw.decode("utf-8", errors="replace")
        return parse_disk_info(text)

    async def set_disk_attributes(
        self,
        path: Path,
        *,
        disk_name: str | None = None,
        write_protected: bool | None = None,
    ) -> None:
        self.calls.append(f"set_disk_attributes({path}, {disk_name}, {write_protected})")
        if not path.exists():
            raise CommandFailed("ファイルが存在しません。")

        def _update() -> None:
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            updated: list[str] = []
            for line in lines:
                lowered = line.lower()
                if disk_name is not None and lowered.startswith("disk name"):
                    updated.append(f"Disk Name : {disk_name}")
                elif write_protected is not None and lowered.startswith("protect"):
                    updated.append(f"Protect : {'on' if write_protected else 'off'}")
                else:
                    updated.append(line)
            path.write_text("\n".join(updated) + "\n", encoding="utf-8")

        await asyncio.to_thread(_update)

    # --- システム操作 -------------------------------------------------------

    async def reboot(self) -> None:
        # mock では実際には再起動しない
        self.calls.append("reboot")
        self.reboot_requested = True
        logger.info("mock: 再起動が要求されました（実際には何もしません）")

    async def poweroff(self) -> None:
        self.calls.append("poweroff")
        self.poweroff_requested = True
        logger.info("mock: シャットダウンが要求されました（実際には何もしません）")

    async def restart_service(self) -> None:
        self.calls.append("restart_service")
        self.service_restart_requested = True
        logger.info("mock: サービスの再起動が要求されました（実際には何もしません）")
