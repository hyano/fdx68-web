"""ドライブ操作（挿入・排出・ライトプロテクト）。"""

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field

from app.deps import FDX68ServiceDep, StatusMonitorDep
from app.models.drive import FDX68Status

router = APIRouter(prefix="/api/drives", tags=["drives"])

DriveId = Path(description="ドライブ番号（0 または 1）", ge=0, le=1)


class InsertRequest(BaseModel):
    path: str = Field(description="イメージルートからの相対パス")


class ProtectRequest(BaseModel):
    enabled: bool = Field(
        description="ライトプロテクトを有効にするか。"
        "これは fddemu の実行時状態であり、FDX ファイル自体の属性とは別物"
    )


@router.post("/{drive_id}/insert", response_model=FDX68Status)
async def insert(
    request: InsertRequest,
    service: FDX68ServiceDep,
    monitor: StatusMonitorDep,
    drive_id: int = DriveId,
) -> FDX68Status:
    """ドライブにディスクイメージを挿入する。"""
    await service.insert(drive_id, request.path)
    return await monitor.refresh()


@router.post("/{drive_id}/eject", response_model=FDX68Status)
async def eject(
    service: FDX68ServiceDep,
    monitor: StatusMonitorDep,
    drive_id: int = DriveId,
) -> FDX68Status:
    """ドライブからディスクイメージを排出する。"""
    await service.eject(drive_id)
    return await monitor.refresh()


@router.post("/{drive_id}/protect", response_model=FDX68Status)
async def set_protect(
    request: ProtectRequest,
    service: FDX68ServiceDep,
    monitor: StatusMonitorDep,
    drive_id: int = DriveId,
) -> FDX68Status:
    """ライトプロテクト（実行時状態）を設定する。"""
    await service.set_write_protect(drive_id, request.enabled)
    return await monitor.refresh()
