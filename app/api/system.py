"""Raspberry Pi のシステム操作。

**X68000 が動作中の可能性があるため、Web UI 側で必ず確認ダイアログを表示すること。**
"""

from fastapi import APIRouter

from app.deps import SystemServiceDep

router = APIRouter(prefix="/api/system", tags=["system"])


@router.post("/reboot")
async def reboot(service: SystemServiceDep) -> dict[str, str]:
    """Raspberry Pi を再起動する。"""
    await service.reboot()
    return {"message": "再起動を開始しました。"}


@router.post("/poweroff")
async def poweroff(service: SystemServiceDep) -> dict[str, str]:
    """Raspberry Pi をシャットダウンする。"""
    await service.poweroff()
    return {"message": "シャットダウンを開始しました。"}


@router.post("/restart-service")
async def restart_service(service: SystemServiceDep) -> dict[str, str]:
    """Web UI 自身のサービスを再起動する。主に開発中の再読み込み用。

    fddemu は unit の KillMode=process により再起動をまたいで生き残るので、
    X68000 から見えているドライブは維持される。
    """
    await service.restart_service()
    return {"message": "Web UI サービスを再起動しています。"}
