"""依存性注入。

アプリケーション全体で 1 組のバックエンド・サービスを共有する。
FastAPI のハンドラはここから受け取る。
"""

from typing import Annotated

from fastapi import Depends, Request

from app.backends.base import FDX68Backend
from app.config import Settings
from app.monitoring.status_monitor import ConnectionManager, StatusMonitor
from app.services.fdx68_service import FDX68Service
from app.services.image_service import ImageService
from app.services.system_service import SystemService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_backend(request: Request) -> FDX68Backend:
    return request.app.state.backend


def get_image_service(request: Request) -> ImageService:
    return request.app.state.image_service


def get_fdx68_service(request: Request) -> FDX68Service:
    return request.app.state.fdx68_service


def get_system_service(request: Request) -> SystemService:
    return request.app.state.system_service


def get_status_monitor(request: Request) -> StatusMonitor:
    return request.app.state.status_monitor


def get_connection_manager(request: Request) -> ConnectionManager:
    return request.app.state.connection_manager


SettingsDep = Annotated[Settings, Depends(get_settings)]
BackendDep = Annotated[FDX68Backend, Depends(get_backend)]
ImageServiceDep = Annotated[ImageService, Depends(get_image_service)]
FDX68ServiceDep = Annotated[FDX68Service, Depends(get_fdx68_service)]
SystemServiceDep = Annotated[SystemService, Depends(get_system_service)]
StatusMonitorDep = Annotated[StatusMonitor, Depends(get_status_monitor)]
