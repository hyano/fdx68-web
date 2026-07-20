"""Raspberry Pi のシステム操作。

**X68000 が動作中の可能性があるため、これらの操作には必ず確認を取ること。**
確認ダイアログの表示は Web UI 側の責務。
"""

import logging

from app.backends.base import FDX68Backend

logger = logging.getLogger(__name__)


class SystemService:
    """再起動とシャットダウン。"""

    def __init__(self, backend: FDX68Backend) -> None:
        self._backend = backend

    async def reboot(self) -> None:
        logger.warning("再起動が要求されました")
        await self._backend.reboot()

    async def poweroff(self) -> None:
        logger.warning("シャットダウンが要求されました")
        await self._backend.poweroff()
