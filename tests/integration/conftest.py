"""Integration Test の共通フィクスチャ。

Mock バックエンドで FastAPI アプリ全体を動かす。実際の FDX68 コマンドは呼ばない。
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
def image_root(tmp_path: Path) -> Path:
    """テスト用のイメージディレクトリを用意する。

    ツリー表示と自然順ソートを確認できるよう、階層と複数枚組の命名を含める。
    """
    root = tmp_path / "fdximg"
    root.mkdir()

    (root / "disk1.fdx").write_bytes(b"FDX68-MOCK-IMAGE\nDisk Name : DISK1\n")
    (root / "source.d88").write_bytes(b"D88-DUMMY")
    (root / "readme.txt").write_text("メモ", encoding="utf-8")

    game = root / "ゲーム"
    game.mkdir()
    for index in (1, 2, 10):
        (game / f"disk{index}.fdx").write_bytes(b"FDX68-MOCK-IMAGE\n")

    (game / "sub").mkdir()
    (game / "sub" / "nested.fdx").write_bytes(b"FDX68-MOCK-IMAGE\n")

    (root / "empty").mkdir()

    return root


@pytest.fixture
def settings(image_root: Path) -> Settings:
    return Settings(
        backend="mock",
        image_dir=image_root,
        status_interval=60.0,  # テスト中に勝手にポーリングさせない
        max_upload_mb=1,
    )


@pytest_asyncio.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    """lifespan を動かした状態のクライアントを返す。"""
    app = create_app(settings)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        # lifespan を手動で起動する（ASGITransport は自動で呼ばないため）
        async with app.router.lifespan_context(app):
            async_client.app = app  # type: ignore[attr-defined]
            yield async_client


@pytest_asyncio.fixture
async def running_client(client: AsyncClient) -> AsyncClient:
    """fddemu が起動している状態のクライアント。"""
    await client.post("/api/fddemu/start", json={})
    return client
