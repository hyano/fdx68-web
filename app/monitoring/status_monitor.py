"""ドライブ状態の監視と WebSocket へのブロードキャスト。

fddemu は GPIO のビットバンギングで FDD 信号を生成しており、タイミングにシビアである。
ポーリングは fork/exec を伴うためジッタの要因になりうるので、無駄な実行は避ける。
"""

import asyncio
import contextlib
import logging
from typing import Any, Protocol

from app.models.drive import FDX68Status
from app.services.fdx68_service import FDX68Service

logger = logging.getLogger(__name__)


class JsonSocket(Protocol):
    """JSON を送信できる接続。

    FastAPI の `WebSocket` がこれを満たす。
    監視層が FastAPI に依存しないよう、具象型ではなく振る舞いで受ける。
    """

    async def send_json(self, data: dict[str, Any]) -> None: ...


#: WebSocket クライアントが 0 件のときのポーリング間隔（秒）。
#: 誰も見ていないのに 2 秒ごとに fddctl を叩き続ける必要はない。
IDLE_INTERVAL = 30.0

#: 監視中にエラーが続いた場合に警告を出すまでの回数
_ERROR_LOG_THRESHOLD = 3


class ConnectionManager:
    """WebSocket 接続の管理とブロードキャスト。"""

    def __init__(self) -> None:
        self._connections: set[JsonSocket] = set()
        self._lock = asyncio.Lock()

    @property
    def count(self) -> int:
        return len(self._connections)

    async def connect(self, websocket: JsonSocket) -> None:
        async with self._lock:
            self._connections.add(websocket)
        logger.debug("WebSocket が接続しました（現在 %d 件）", self.count)

    async def disconnect(self, websocket: JsonSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
        logger.debug("WebSocket が切断しました（現在 %d 件）", self.count)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """全クライアントに送信する。

        送信に失敗した接続は取り除く。1 つの切断が他のクライアントへの
        配信を止めないようにする。
        """
        async with self._lock:
            targets = list(self._connections)

        dead: list[JsonSocket] = []
        for connection in targets:
            try:
                await connection.send_json(message)
            except Exception:  # noqa: BLE001  切断は通常起こりうる
                dead.append(connection)

        if dead:
            async with self._lock:
                for connection in dead:
                    self._connections.discard(connection)
            logger.debug("切断済みの WebSocket を %d 件除去しました", len(dead))


class StatusMonitor:
    """定期的に状態を取得し、変化があったときだけ通知する。"""

    def __init__(
        self,
        service: FDX68Service,
        manager: ConnectionManager,
        interval: float,
    ) -> None:
        self._service = service
        self._manager = manager
        self._interval = interval
        self._task: asyncio.Task[None] | None = None
        self._latest: FDX68Status | None = None
        self._error_count = 0

    @property
    def latest(self) -> FDX68Status | None:
        """最後に取得した状態。新規接続時に即座に返すために使う。"""
        return self._latest

    async def refresh(self) -> FDX68Status:
        """状態を取得して保持する。変化があれば通知する。"""
        status = await self._service.get_status()

        # 変化があったときだけ送る。毎回送ると無駄な通信とレンダリングが発生する。
        if self._latest is None or self._latest != status:
            self._latest = status
            await self._manager.broadcast({"type": "status", **status.model_dump()})
        else:
            self._latest = status

        return status

    async def notify_images_changed(self, path: str) -> None:
        """ファイル操作をほかのクライアントに通知する。

        複数のタブや端末で開いていても表示が食い違わないようにするため。
        """
        await self._manager.broadcast({"type": "images_changed", "path": path})

    def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("状態監視を開始しました（間隔 %.1f 秒）", self._interval)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("状態監視を停止しました")

    async def _loop(self) -> None:
        while True:
            try:
                await self.refresh()
                self._error_count = 0
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                # 監視は動き続ける必要があるため、1 回の失敗で止めない。
                # ログが溢れないよう、連続失敗時のみ警告に格上げする。
                self._error_count += 1
                if self._error_count == _ERROR_LOG_THRESHOLD:
                    logger.warning("状態の取得が連続して失敗しています", exc_info=True)
                else:
                    logger.debug("状態の取得に失敗しました", exc_info=True)

            # 誰も見ていないときはポーリングを緩める
            interval = self._interval if self._manager.count > 0 else IDLE_INTERVAL
            await asyncio.sleep(interval)
