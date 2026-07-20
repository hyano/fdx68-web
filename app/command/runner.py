"""subprocess の実行を集約する層。

ここ以外で subprocess を呼ばないこと。
`shell=True` は使わず、必ず引数リスト形式で実行する。
"""

import asyncio
import logging
import os
import subprocess  # noqa: S404  引数リスト形式でのみ使う
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 子プロセスに渡す環境変数。
# 周囲のロケール設定（systemd 経由か対話 SSH かで異なる）に解釈を左右させないため、
# UTF-8 を明示的に固定する。日本語ファイル名のイメージを扱うために必要。
_CHILD_ENV = {
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PYTHONUTF8": "1",
}


@dataclass
class CommandResult:
    """コマンドの実行結果。"""

    args: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        """標準出力と標準エラー出力を結合したもの。

        FDX68 のコマンドはエラーを標準出力に書くことがあるため、
        エラー判定では両方を見る必要がある。
        """
        if self.stderr:
            return f"{self.stdout}\n{self.stderr}".strip()
        return self.stdout


class CommandRunner(ABC):
    """コマンド実行の抽象。"""

    @abstractmethod
    async def run(self, args: list[str], *, timeout: float = 30.0) -> CommandResult:
        """コマンドを実行して結果を返す。"""

    @abstractmethod
    async def spawn(self, args: list[str]) -> int:
        """コマンドをバックグラウンドで起動し、PID を返す。"""


class SubprocessCommandRunner(CommandRunner):
    """実際に subprocess でコマンドを実行する。"""

    async def run(self, args: list[str], *, timeout: float = 30.0) -> CommandResult:
        logger.debug("コマンドを実行します: %s", args)

        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, **_CHILD_ENV},
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            logger.error("コマンドがタイムアウトしました: %s", args)
            raise

        # errors="replace" にしているのは、想定外のバイト列が混じっても
        # デコード例外で状態監視ループを止めないため。
        # 監視は 2 秒ごとに動き続けるので、1 回の失敗でアプリを停止させない。
        result = CommandResult(
            args=args,
            returncode=process.returncode or 0,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
        )
        logger.debug("終了コード %d: %s", result.returncode, result.output[:200])
        return result

    async def spawn(self, args: list[str]) -> int:
        """バックグラウンドで起動する（fddemu 用）。

        fddemu は起動したまま動き続けるため、完了を待たない。
        """
        logger.info("バックグラウンドで起動します: %s", args)

        # 親プロセス（uvicorn）の終了に巻き込まれないよう、新しいセッションで起動する。
        process = subprocess.Popen(  # noqa: S603  引数リスト形式、shell=False
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            env={**os.environ, **_CHILD_ENV},
        )
        return process.pid


@dataclass
class FakeCommandRunner(CommandRunner):
    """テスト用。実行されたコマンドを記録し、あらかじめ設定した結果を返す。"""

    #: args のタプルをキーとした応答の設定
    responses: dict[tuple[str, ...], CommandResult] = field(default_factory=dict)
    #: args のタプルをキーとした、呼び出し順に消費される応答の列。
    #: 「1 回目は失敗、2 回目以降は成功」のような時系列を再現するために使う。
    #: 空になったら responses → default_result の順にフォールバックする。
    sequences: dict[tuple[str, ...], list[CommandResult]] = field(default_factory=dict)
    #: 実行されたコマンドの履歴
    calls: list[list[str]] = field(default_factory=list)
    #: 設定がない場合に返す既定の結果
    default_result: CommandResult | None = None
    spawned: list[list[str]] = field(default_factory=list)
    next_pid: int = 1000

    async def run(self, args: list[str], *, timeout: float = 30.0) -> CommandResult:
        self.calls.append(list(args))
        key = tuple(args)
        queue = self.sequences.get(key)
        if queue:
            return queue.pop(0)
        if key in self.responses:
            return self.responses[key]
        if self.default_result is not None:
            return self.default_result
        return CommandResult(args=list(args), returncode=0, stdout="", stderr="")

    async def spawn(self, args: list[str]) -> int:
        self.spawned.append(list(args))
        self.next_pid += 1
        return self.next_pid
