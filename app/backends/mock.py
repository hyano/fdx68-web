"""開発・テスト用バックエンド。

実際の FDX68 コマンドを呼ばず、メモリ上の状態を操作する。
macOS 上での開発と、CI での Integration Test に使う。

ファイルを実際に作る操作（変換・ブランク作成）については、
後続の処理が「ファイルが存在すること」を前提にするため、
中身は簡易的なものでも実際にファイルを作成する。
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.backends.base import FDX68Backend
from app.errors import CommandFailed, FddemuNotRunning, InvalidParameter, NotFound
from app.models.drive import Drive, FDX68Status
from app.models.image import AnalyzeMode, DataFormat, DiskInfo, DiskType

logger = logging.getLogger(__name__)

#: mock が生成するファイルの先頭に置く目印。実際の FDX68 形式ではない。
_MOCK_HEADER = "FDX68-MOCK-IMAGE\n"

#: 2HD は 360rpm、それ以外は 300rpm（X68000 で使うのは 2HD）
_RPM_BY_DISK_TYPE = {DiskType.TWO_HD: 360}
_DEFAULT_RPM = 300


def mock_image_bytes(
    *,
    disk_name: str = "BLANK IMAGE",
    disk_type: DiskType = DiskType.TWO_HD,
    write_protected: bool = False,
    data_format: DataFormat = DataFormat.ENCODE,
) -> bytes:
    """mock が扱うディスクイメージのバイト列を組み立てる。

    **これは mock 独自の形式であり、FDX68 の形式ではない。**

    以前は fdxtool の出力を模したテキストを書き、それを本物のパーサーで
    読み戻していた。その作りだと mock が FDX68 の出力書式に縛られ、
    実機側の書式が変われば mock とテストのフィクスチャが道連れで壊れる。
    mock は自分の形式だけを知っていればよいので、独自の JSON にしている。

    テストのフィクスチャからも使えるよう公開している。
    """
    payload = {
        "disk_name": disk_name,
        "disk_type": disk_type.value,
        "write_protected": write_protected,
        "data_format": data_format.value,
    }
    return _MOCK_HEADER.encode() + json.dumps(payload, ensure_ascii=False, indent=2).encode()


def _decode_mock_image(raw: bytes) -> DiskInfo:
    """mock 形式のバイト列から DiskInfo を組み立てる。

    mock が作ったものでない場合（開発中に手で置いたファイル等）は、
    解析できなかった実機と同じく、生の内容だけを保持した DiskInfo を返す。
    """
    text = raw.decode("utf-8", errors="replace")

    if not text.startswith(_MOCK_HEADER):
        return DiskInfo(raw_output=text)

    try:
        payload = json.loads(text[len(_MOCK_HEADER) :])
    except ValueError:
        return DiskInfo(raw_output=text)

    disk_type = payload.get("disk_type")
    return DiskInfo(
        name=payload.get("disk_name"),
        disk_type=disk_type,
        rpm=_RPM_BY_DISK_TYPE.get(DiskType(disk_type), _DEFAULT_RPM) if disk_type else None,
        cylinders=77,
        heads=2,
        data_format=payload.get("data_format"),
        write_protected=payload.get("write_protected"),
        raw_output=text,
    )


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

    def _require_drive(self, drive_id: int) -> _MockDrive:
        """操作対象のドライブを返す。

        例外の種類は Real バックエンドと揃えること。
        ここがずれると、mock で通ったテストが実機で別のステータスになる。
        """
        if not self.fddemu_running:
            raise FddemuNotRunning()

        drive = self.drives.get(drive_id)
        if drive is None:
            raise InvalidParameter(f"ドライブ {drive_id} は存在しません。")
        return drive

    async def insert(self, drive_id: int, image_path: Path) -> None:
        self.calls.append(f"insert({drive_id}, {image_path})")
        drive = self._require_drive(drive_id)
        if not image_path.exists():
            raise NotFound("指定されたファイルを開けませんでした。")
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
            raise NotFound("変換元のファイルが存在しません。")

        # 実際の変換は行わないが、後続処理のためにファイルは作る。
        # 元ファイルを変更しないことは実機と同じ。
        await asyncio.to_thread(
            destination.write_bytes,
            mock_image_bytes(disk_name=source.stem, data_format=data_format),
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
        content = mock_image_bytes(
            disk_name=disk_name or "BLANK IMAGE",
            disk_type=disk_type,
            write_protected=write_protected,
            data_format=data_format,
        )
        await asyncio.to_thread(destination.write_bytes, content)

    async def get_disk_info(self, path: Path) -> DiskInfo:
        self.calls.append(f"get_disk_info({path})")
        if not path.exists():
            raise NotFound()

        raw = await asyncio.to_thread(path.read_bytes)
        return _decode_mock_image(raw)

    async def set_disk_attributes(
        self,
        path: Path,
        *,
        disk_name: str | None = None,
        write_protected: bool | None = None,
    ) -> None:
        self.calls.append(f"set_disk_attributes({path}, {disk_name}, {write_protected})")
        if not path.exists():
            raise NotFound()

        def _update() -> None:
            current = _decode_mock_image(path.read_bytes())
            path.write_bytes(
                mock_image_bytes(
                    disk_name=disk_name if disk_name is not None else (current.name or ""),
                    disk_type=DiskType(current.disk_type) if current.disk_type else DiskType.TWO_HD,
                    write_protected=(
                        write_protected
                        if write_protected is not None
                        else bool(current.write_protected)
                    ),
                    data_format=(
                        DataFormat(current.data_format)
                        if current.data_format
                        else DataFormat.ENCODE
                    ),
                )
            )

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
