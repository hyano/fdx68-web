"""FastAPI アプリケーション本体。"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import drives, images, status, system, ws
from app.backends.factory import create_backend
from app.config import Settings, get_settings
from app.errors import FDX68Error
from app.monitoring.status_monitor import ConnectionManager, StatusMonitor
from app.services.fdx68_service import FDX68Service
from app.services.image_service import ImageService
from app.services.system_service import SystemService

logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """起動時にサービスを組み立て、状態監視を開始する。"""
    settings: Settings = app.state.settings

    logger.info(
        "FDX68 Web Controller を起動します（バックエンド: %s, イメージ: %s）",
        settings.backend,
        settings.image_dir,
    )

    if not settings.image_dir.exists():
        logger.warning("イメージディレクトリが存在しません: %s", settings.image_dir)

    backend = create_backend(settings)
    image_service = ImageService(settings, backend)
    fdx68_service = FDX68Service(settings, backend, image_service)
    system_service = SystemService(backend)
    connection_manager = ConnectionManager()
    status_monitor = StatusMonitor(fdx68_service, connection_manager, settings.status_interval)

    app.state.backend = backend
    app.state.image_service = image_service
    app.state.fdx68_service = fdx68_service
    app.state.system_service = system_service
    app.state.connection_manager = connection_manager
    app.state.status_monitor = status_monitor

    status_monitor.start()
    try:
        yield
    finally:
        await status_monitor.stop()
        logger.info("FDX68 Web Controller を停止しました")


def create_app(settings: Settings | None = None) -> FastAPI:
    """アプリケーションを生成する。

    テストからは settings を差し替えて呼べるようにしている。
    """
    _configure_logging()

    app = FastAPI(
        title="FDX68 Web Controller",
        description="X68000 に接続した FDX68 をブラウザから操作するためのコントローラ",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings or get_settings()

    app.include_router(status.router)
    app.include_router(drives.router)
    app.include_router(images.router)
    app.include_router(system.router)
    app.include_router(ws.router)

    @app.exception_handler(FDX68Error)
    async def handle_fdx68_error(_: Request, exc: FDX68Error) -> JSONResponse:
        """アプリケーション例外を HTTP レスポンスに変換する。

        利用者には日本語のメッセージだけを返し、技術的な詳細はログに残す。
        """
        if exc.detail:
            logger.info("%s: %s", exc.message, exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"message": exc.message},
        )

    _mount_frontend(app)

    return app


def _mount_frontend(app: FastAPI) -> None:
    """フロントエンドの静的ファイルを配信する。"""
    if not FRONTEND_DIR.exists():
        logger.warning("フロントエンドが見つかりません: %s", FRONTEND_DIR)
        return

    # 装飾用アセットは長めにキャッシュさせる（画像を増やしても負荷が増えないように）
    assets_dir = FRONTEND_DIR / "assets"
    if assets_dir.exists():
        app.mount(
            "/assets",
            StaticFiles(directory=assets_dir),
            name="assets",
        )

    for name in ("css", "js"):
        directory = FRONTEND_DIR / name
        if directory.exists():
            app.mount(f"/{name}", StaticFiles(directory=directory), name=name)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        # HTML はキャッシュさせない（更新が即座に反映されるように）
        return FileResponse(
            FRONTEND_DIR / "index.html",
            headers={"Cache-Control": "no-cache"},
        )


app = create_app()
