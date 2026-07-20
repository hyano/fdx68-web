"""バックエンドの生成。

`platform.system()` による分岐をコード中に散在させないため、
バックエンドの選択はここ 1 箇所に閉じ込める。
"""

import logging

from app.backends.base import FDX68Backend
from app.backends.mock import MockFDX68Backend
from app.backends.real import RealFDX68Backend
from app.command.runner import SubprocessCommandRunner
from app.config import Settings

logger = logging.getLogger(__name__)


def create_backend(settings: Settings) -> FDX68Backend:
    """設定に応じたバックエンドを返す。"""
    if settings.backend == "mock":
        logger.info("Mock バックエンドを使用します（FDX68 コマンドは実行されません）")
        return MockFDX68Backend()

    logger.info("Real バックエンドを使用します（FDX68 コマンドを実行します）")
    return RealFDX68Backend(settings, SubprocessCommandRunner())
