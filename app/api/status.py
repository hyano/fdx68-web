"""状態取得と fddemu の制御。"""

import time

from fastapi import APIRouter
from pydantic import BaseModel

from app.deps import FDX68ServiceDep, SettingsDep, StatusMonitorDep
from app.models.drive import FDX68Status

router = APIRouter(prefix="/api", tags=["status"])

# プロセスの起動時刻。モジュールの読み込み時に一度だけ決まる。
#
# Web UI から自分自身のサービスを再起動したあと、フロントエンドが
# 「別のプロセスが立ち上がった」ことを判定するために使う。
# 「health が落ちるのを待つ」方式では、再起動が速いと落下を観測できずに
# 取りこぼすため、値の変化で見る。
_STARTED_AT = time.time()


class HealthResponse(BaseModel):
    status: str
    backend: str
    started_at: float


class StartRequest(BaseModel):
    options: str | None = None


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    """疎通確認。デプロイスクリプトとインストーラが使う。"""
    return HealthResponse(status="ok", backend=settings.backend, started_at=_STARTED_AT)


@router.get("/status", response_model=FDX68Status)
async def get_status(monitor: StatusMonitorDep) -> FDX68Status:
    """現在のドライブ状態を返す。

    fddemu が停止していてもエラーにはせず、`fddemu_running=false` を返す。
    """
    return await monitor.refresh()


@router.post("/fddemu/start", response_model=FDX68Status)
async def start_fddemu(
    request: StartRequest,
    service: FDX68ServiceDep,
    monitor: StatusMonitorDep,
) -> FDX68Status:
    """fddemu を起動する。"""
    await service.start_fddemu(request.options)
    return await monitor.refresh()


@router.post("/fddemu/stop", response_model=FDX68Status)
async def stop_fddemu(
    service: FDX68ServiceDep,
    monitor: StatusMonitorDep,
) -> FDX68Status:
    """fddemu を停止する。

    X68000 がディスクにアクセス中の可能性があるため、
    Web UI 側で確認ダイアログを表示すること。
    """
    await service.stop_fddemu()
    return await monitor.refresh()
