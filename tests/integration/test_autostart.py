"""Web UI 起動時に fddemu を自動起動する設定の Integration Test。

既定の `client`/`settings` フィクスチャは autostart_fddemu=False 固定なので、
ここでは個別の Settings で lifespan を起動する。
"""

from pathlib import Path

from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app


async def test_起動時に自動的に起動する(image_root: Path):
    settings = Settings(backend="mock", image_dir=image_root, status_interval=60.0)
    app = create_app(settings)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            response = await client.get("/api/status")

    assert response.status_code == 200
    assert response.json()["fddemu_running"] is True
