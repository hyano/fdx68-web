"""WebSocket による状態通知。"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.deps import get_connection_manager, get_status_monitor

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/status")
async def status_websocket(websocket: WebSocket) -> None:
    """状態変化を通知する。

    送るメッセージは封筒形式で、種類を後から増やせるようにしている。

    - ``{"type": "status", ...}``          ドライブ状態（変化があったときのみ）
    - ``{"type": "images_changed", ...}``  ファイル操作の通知
    """
    manager = get_connection_manager(websocket)  # type: ignore[arg-type]
    monitor = get_status_monitor(websocket)  # type: ignore[arg-type]

    await websocket.accept()
    await manager.connect(websocket)

    try:
        # 接続直後に現在の状態を 1 回送る。
        # 次の変化が起きるまで何も表示されない、という状態を避けるため。
        status = monitor.latest
        if status is None:
            status = await monitor.refresh()
        await websocket.send_json({"type": "status", **status.model_dump()})

        # クライアントからの受信は使わないが、切断を検知するために待ち受ける
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001  切断時の例外は通常起こりうる
        logger.debug("WebSocket でエラーが発生しました", exc_info=True)
    finally:
        await manager.disconnect(websocket)
