"""依存性注入。

アプリケーション全体で 1 組のバックエンド・サービスを共有する。
FastAPI のハンドラはここから受け取る。

HTTPConnection で受けるのは、Request（HTTP）と WebSocket の共通基底だからである。
どちらも .app.state を読むだけなので、WebSocket ハンドラからも同じ関数を使える。
"""

from typing import Annotated

from fastapi import Depends
from starlette.requests import HTTPConnection

from app.backends.base import FDX68Backend
from app.config import Settings
from app.monitoring.status_monitor import ConnectionManager, StatusMonitor
from app.services.fdx68_service import FDX68Service
from app.services.image_service import ImageService
from app.services.system_service import SystemService


def get_settings(connection: HTTPConnection) -> Settings:
    return connection.app.state.settings


def get_backend(connection: HTTPConnection) -> FDX68Backend:
    return connection.app.state.backend


def get_image_service(connection: HTTPConnection) -> ImageService:
    return connection.app.state.image_service


def get_fdx68_service(connection: HTTPConnection) -> FDX68Service:
    return connection.app.state.fdx68_service


def get_system_service(connection: HTTPConnection) -> SystemService:
    return connection.app.state.system_service


def get_status_monitor(connection: HTTPConnection) -> StatusMonitor:
    return connection.app.state.status_monitor


def get_connection_manager(connection: HTTPConnection) -> ConnectionManager:
    return connection.app.state.connection_manager


SettingsDep = Annotated[Settings, Depends(get_settings)]
BackendDep = Annotated[FDX68Backend, Depends(get_backend)]
ImageServiceDep = Annotated[ImageService, Depends(get_image_service)]
FDX68ServiceDep = Annotated[FDX68Service, Depends(get_fdx68_service)]
SystemServiceDep = Annotated[SystemService, Depends(get_system_service)]
StatusMonitorDep = Annotated[StatusMonitor, Depends(get_status_monitor)]
