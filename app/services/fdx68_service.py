"""ドライブ操作と fddemu 制御の業務ロジック。"""

import logging
from pathlib import Path

from app.backends.base import FDX68Backend
from app.config import Settings
from app.errors import InvalidParameter, NotFound, UnsupportedFileType
from app.models.drive import FDX68Status
from app.models.image import ImageKind
from app.services.image_service import ImageService, classify

logger = logging.getLogger(__name__)

#: FDX68 がエミュレーションできるドライブ数
VALID_DRIVE_IDS = (0, 1)


class FDX68Service:
    """ドライブ操作と fddemu の制御。"""

    def __init__(self, settings: Settings, backend: FDX68Backend, images: ImageService) -> None:
        self._settings = settings
        self._backend = backend
        self._images = images

    async def get_status(self) -> FDX68Status:
        """現在の状態を返す。

        挿入中のイメージについて、イメージルートからの相対パスも埋める。
        Web UI がツリー上の該当行に印を付けるために使う。
        """
        status = await self._backend.get_status()

        for drive in status.drives:
            if not drive.image:
                continue
            drive.image_relative = self._safe_relative(drive.image)

        return status

    def _safe_relative(self, absolute: str) -> str | None:
        """絶対パスをイメージルートからの相対パスに変換する。

        ルート外のイメージが挿入されている場合（SSH から直接挿入された等）は
        None を返す。エラーにはしない。
        """
        try:
            return self._images.to_relative(Path(absolute))
        except (ValueError, OSError):
            return None

    # --- fddemu の制御 ------------------------------------------------------

    async def start_fddemu(self, options: str | None = None) -> FDX68Status:
        await self._backend.start_fddemu(options)
        return await self.get_status()

    async def stop_fddemu(self) -> FDX68Status:
        await self._backend.stop_fddemu()
        return await self.get_status()

    # --- ドライブ操作 -------------------------------------------------------

    @staticmethod
    def _validate_drive_id(drive_id: int) -> None:
        if drive_id not in VALID_DRIVE_IDS:
            raise InvalidParameter(f"ドライブ番号は {VALID_DRIVE_IDS} のいずれかです。")

    async def insert(self, drive_id: int, relative: str) -> FDX68Status:
        """ドライブにディスクイメージを挿入する。"""
        self._validate_drive_id(drive_id)

        target = self._images.resolve(relative)

        # 外部で削除されている場合がある（SSH や rsync による変更）。
        # これは異常ではないので、分かりやすいエラーを返す。
        if not target.exists():
            raise NotFound(f"「{Path(relative).name}」が見つかりません。")

        if classify(target) is not ImageKind.FDX:
            # 利用者の選択ミスであってサーバーの障害ではないので 400 を返す。
            # 同じ条件は image_service の情報取得・属性変更でも
            # UnsupportedFileType として扱っており、そちらと揃えている。
            raise UnsupportedFileType(
                "FDX 形式のイメージのみ挿入できます。他の形式は先に FDX へ変換してください。"
            )

        await self._backend.insert(drive_id, target)
        logger.info("Drive %d に挿入しました: %s", drive_id, target)
        return await self.get_status()

    async def eject(self, drive_id: int) -> FDX68Status:
        self._validate_drive_id(drive_id)
        await self._backend.eject(drive_id)
        logger.info("Drive %d をイジェクトしました", drive_id)
        return await self.get_status()

    async def set_write_protect(self, drive_id: int, enabled: bool) -> FDX68Status:
        """ライトプロテクト（fddemu の実行時状態）を設定する。

        FDX ファイル自体の属性を変える set_attributes とは別物。
        """
        self._validate_drive_id(drive_id)
        await self._backend.set_write_protect(drive_id, enabled)
        return await self.get_status()
