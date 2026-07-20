"""Web UI 起動時の fddemu 自動起動ロジックのテスト。

mock バックエンドを直接操作し、app.main._autostart_fddemu の分岐を検証する。
"""

from pathlib import Path

import pytest

from app.backends.mock import MockFDX68Backend
from app.config import Settings
from app.main import _autostart_fddemu
from app.services.fdx68_service import FDX68Service
from app.services.image_service import ImageService


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(backend="mock", image_dir=tmp_path)


@pytest.fixture
def backend() -> MockFDX68Backend:
    return MockFDX68Backend()


@pytest.fixture
def fdx68_service(settings: Settings, backend: MockFDX68Backend) -> FDX68Service:
    return FDX68Service(settings, backend, ImageService(settings, backend))


async def test_停止中なら起動する(backend: MockFDX68Backend, fdx68_service: FDX68Service):
    await _autostart_fddemu(backend, fdx68_service)

    assert backend.fddemu_running is True


async def test_既に起動中ならスキップする(backend: MockFDX68Backend, fdx68_service: FDX68Service):
    backend.fddemu_running = True

    await _autostart_fddemu(backend, fdx68_service)

    # start_fddemu が呼ばれていれば例外になるはずなので、呼ばれていないことを確認する
    assert "start_fddemu(None)" not in backend.calls
    assert backend.fddemu_running is True


async def test_起動に失敗しても例外を送出しない(
    backend: MockFDX68Backend,
    fdx68_service: FDX68Service,
    monkeypatch: pytest.MonkeyPatch,
):
    async def _fail(options: str | None = None) -> None:
        from app.errors import CommandFailed

        raise CommandFailed("fddemu を起動できませんでした。")

    monkeypatch.setattr(backend, "start_fddemu", _fail)

    await _autostart_fddemu(backend, fdx68_service)  # 例外にならないことを確認する
