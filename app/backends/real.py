"""実機用バックエンド。実際の FDX68 コマンドを実行する。

**macOS ではこれを使わないこと。** 開発時は mock を使う。
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.backends.base import FDX68Backend
from app.command.parser import check_command_error, parse_device_list, parse_disk_info
from app.command.runner import CommandRunner
from app.config import Settings
from app.errors import CommandFailed, FddemuNotRunning
from app.models.drive import FDX68Status
from app.models.image import AnalyzeMode, DataFormat, DiskInfo, DiskType

logger = logging.getLogger(__name__)

#: fddemu の起動確認をあきらめるまでの秒数（Pi 3 A+ の実測に余裕を持たせた値）
_STARTUP_TIMEOUT = 15.0
#: fddemu の停止確認をあきらめ、pkill へ移行するまでの秒数
_STOP_TIMEOUT = 5.0
#: 起動／停止の確認ポーリング間隔
_POLL_INTERVAL = 0.5
#: 変換は大きなイメージだと時間がかかるため長めに取る
_CONVERT_TIMEOUT = 300.0
#: Web UI 自身の systemd unit 名。scripts/install.sh の SERVICE_NAME と一致させること。
_SERVICE_UNIT = "fdx68-web.service"


async def _poll_until(
    condition: Callable[[], Awaitable[bool]], *, timeout: float, interval: float
) -> bool:
    """condition が真になるまで待つ。真になれば True、timeout に達したら False。

    最初の判定は待たずに即実行する（応答が速いケースで無駄な待ちを入れないため）。
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        if await condition():
            return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(interval)


class RealFDX68Backend(FDX68Backend):
    """実際の FDX68 コマンドを呼ぶバックエンド。"""

    def __init__(self, settings: Settings, runner: CommandRunner) -> None:
        self._settings = settings
        self._runner = runner

    # --- コマンドの組み立て -------------------------------------------------

    def _privileged(self, *args: str) -> list[str]:
        """root 権限が必要なコマンドを組み立てる。

        対象は fddemu（/dev/mem を使うため root 必須）と、
        pkill / reboot / poweroff / systemctl のシステム操作。

        アプリ自体を root で動かしている場合は sudo が不要になるため、
        FDX68_USE_SUDO で無効にできるようにしている。
        """
        if self._settings.use_sudo:
            return ["sudo", "-n", *args]
        return list(args)

    def _fddctl(self, *args: str) -> list[str]:
        """fddctl のコマンドを組み立てる。

        **fddctl は root 権限を必要としない**（実機で確認済み）。
        fddemu が root で動いていても、非 root のまま IPC ソケットへ接続できる。
        不要な昇格をしないよう、ここでは sudo を付けない。
        """
        return [self._settings.command_path("fddctl"), *args]

    async def _run_checked(self, args: list[str], *, timeout: float = 30.0) -> str:
        """コマンドを実行し、出力にエラーがあれば例外を送出する。

        FDX68 のコマンドはエラー時でも終了コード 0 を返すことがあるため、
        終了コードと出力の両方を確認する。
        """
        result = await self._runner.run(args, timeout=timeout)
        error_line = check_command_error(result.output)

        if error_line is not None or result.returncode != 0:
            detail = f"args={args} rc={result.returncode} output={result.output!r}"
            logger.error("コマンドが失敗しました: %s", detail)
            message = error_line or "コマンドの実行に失敗しました。"
            raise CommandFailed(_friendly_message(message), detail=detail)

        return result.output

    # --- 状態取得 -----------------------------------------------------------

    async def get_status(self) -> FDX68Status:
        result = await self._runner.run(self._fddctl("-l"))
        try:
            return parse_device_list(result.output)
        except FddemuNotRunning:
            # fddemu の停止は異常ではなく通常起こりうる状態なので、
            # エラーにせず「停止中」として返す。
            return FDX68Status(
                fddemu_running=False,
                drives=[],
                message="fddemu が起動していません。",
            )

    async def is_fddemu_running(self) -> bool:
        # -x で完全一致にする。部分一致だと fddemu を含む別プロセスを拾ってしまう。
        result = await self._runner.run(["pgrep", "-x", "fddemu"])
        return result.returncode == 0 and bool(result.stdout.strip())

    # --- fddemu の制御 ------------------------------------------------------

    async def start_fddemu(self, options: str | None = None) -> None:
        if await self.is_fddemu_running():
            raise CommandFailed("fddemu は既に起動しています。")

        args = self._privileged(self._settings.command_path("fddemu"))

        option_string = options if options is not None else self._settings.fddemu_options
        if option_string.strip():
            args.extend(option_string.split())

        await self._runner.spawn(args)

        # 起動直後は fddctl が接続できないため、疎通するまでポーリングする。
        # Pi 3 A+ ではメモリが逼迫しており、疎通までに 1 秒を超えることがある。
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _STARTUP_TIMEOUT
        while True:
            status = await self.get_status()
            if status.fddemu_running:
                return

            if not await self.is_fddemu_running():
                # プロセス自体が消えている場合のみ、本当の起動失敗とみなす。
                raise CommandFailed(
                    "fddemu を起動できませんでした。ログを確認してください。",
                    detail=f"args={args}",
                )

            if loop.time() >= deadline:
                # プロセスは生きているが疎通確認だけが間に合わなかったケース。
                # 状態監視ループが後で追従するので、ここではエラーにしない。
                logger.warning(
                    "fddemu の起動確認がタイムアウトしましたが、プロセスは生存しています: args=%s",
                    args,
                )
                return

            await asyncio.sleep(_POLL_INTERVAL)

    async def stop_fddemu(self) -> None:
        """fddemu を停止する。

        **通常は `fddctl --stop` だけで停止する**（実機で確認済み）。
        以降の pkill は、fddemu が IPC ソケットに応答しなくなった異常時のための
        フォールバックであり、正常時には実行されない。

        `--stop` を先に試すのは、エミュレーション中の突然死を避けるため。
        なお fddemu がハングしている場合はソケット経由の `--stop` が効かないので、
        そのときこそ pkill が必要になる。だから残してある。
        """

        async def _stopped() -> bool:
            return not await self.is_fddemu_running()

        result = await self._runner.run(self._fddctl("--stop"))
        logger.info("fddctl --stop: rc=%d %s", result.returncode, result.output.strip())

        if await _poll_until(_stopped, timeout=_STOP_TIMEOUT, interval=_POLL_INTERVAL):
            return

        # -x で完全一致。部分一致による誤爆を防ぐ。
        logger.warning("fddctl --stop で停止しなかったため pkill を使います")
        await self._runner.run(self._privileged("pkill", "-x", "fddemu"))

        if await _poll_until(_stopped, timeout=_STOP_TIMEOUT, interval=_POLL_INTERVAL):
            return

        logger.warning("pkill でも停止しなかったため SIGKILL を送ります")
        await self._runner.run(self._privileged("pkill", "-x", "-9", "fddemu"))

        if not await _poll_until(_stopped, timeout=_STOP_TIMEOUT, interval=_POLL_INTERVAL):
            raise CommandFailed("fddemu を停止できませんでした。")

    # --- ドライブ操作 -------------------------------------------------------

    async def insert(self, drive_id: int, image_path: Path) -> None:
        await self._run_checked(self._fddctl("-i", str(drive_id), "-c", "insert", str(image_path)))

    async def eject(self, drive_id: int) -> None:
        await self._run_checked(self._fddctl("-i", str(drive_id), "-c", "eject"))

    async def set_write_protect(self, drive_id: int, enabled: bool) -> None:
        """ライトプロテクトを設定する。

        **`fddctl -c protect` は現在の状態を反転させるトグルである**（実機で確認済み）。
        API は「有効／無効」を受け取る形にしているため、現在の状態を読んでから
        希望する状態と異なる場合だけコマンドを実行する。

        これを省いて毎回実行すると、既に希望どおりの状態のときに
        反転させてしまい、実機のライトプロテクトが逆になる。
        """
        status = await self.get_status()
        current = next((d for d in status.drives if d.id == drive_id), None)

        if current is not None and current.write_protected == enabled:
            return

        await self._run_checked(self._fddctl("-i", str(drive_id), "-c", "protect"))

    # --- ディスクイメージの操作 ---------------------------------------------

    async def convert_to_fdx(
        self,
        source: Path,
        destination: Path,
        *,
        disk_no: int = 1,
        data_format: DataFormat = DataFormat.ENCODE,
        analyze: AnalyzeMode = AnalyzeMode.UPD765,
    ) -> None:
        args = [
            self._settings.command_path("fdxconv"),
            "-i",
            str(source),
            "-n",
            str(disk_no),
            "-o",
            str(destination),
            "-f",
            data_format.value,
            "-a",
            analyze.value,
        ]
        await self._run_checked(args, timeout=_CONVERT_TIMEOUT)

    async def create_blank_image(
        self,
        destination: Path,
        *,
        disk_type: DiskType = DiskType.TWO_HD,
        disk_name: str | None = None,
        write_protected: bool = False,
        data_format: DataFormat = DataFormat.ENCODE,
    ) -> None:
        args = [
            self._settings.command_path("fdxtool"),
            "-c",
            "-t",
            disk_type.value,
        ]
        # RPM は指定しない。FDX68 の既定値（2HD なら 360）が X68000 にとって正しい。
        if disk_name:
            args.extend(["-n", disk_name])
        args.extend(["-p", "on" if write_protected else "off"])
        args.extend(["-f", data_format.value])
        args.append(str(destination))

        await self._run_checked(args)

    async def get_disk_info(self, path: Path) -> DiskInfo:
        result = await self._runner.run([self._settings.command_path("fdxtool"), str(path)])
        error_line = check_command_error(result.output)
        if error_line is not None:
            raise CommandFailed(
                "ディスク情報を取得できませんでした。",
                detail=f"{error_line} path={path}",
            )
        return parse_disk_info(result.output)

    async def set_disk_attributes(
        self,
        path: Path,
        *,
        disk_name: str | None = None,
        write_protected: bool | None = None,
    ) -> None:
        args = [self._settings.command_path("fdxtool"), "-s"]
        if disk_name is not None:
            args.extend(["-n", disk_name])
        if write_protected is not None:
            args.extend(["-p", "on" if write_protected else "off"])
        args.append(str(path))

        await self._run_checked(args)

    # --- システム操作 -------------------------------------------------------

    async def reboot(self) -> None:
        await self._runner.spawn(self._privileged("/sbin/reboot"))

    async def poweroff(self) -> None:
        await self._runner.spawn(self._privileged("/sbin/poweroff"))

    async def restart_service(self) -> None:
        # --no-block を付けるのは、systemctl restart の完了を待つと
        # 自分自身が停止させられて HTTP 応答を返せなくなるため。
        # --no-block なら systemd にジョブを登録した時点で戻る。
        #
        # 他のシステム操作と違って spawn() を使わないのは、spawn した子プロセスも
        # この unit の cgroup に属し、停止シグナルでジョブ登録前に殺されうるため。
        # run() で登録の完了を待ってから応答を返す。
        #
        # 引数は packaging/fdx68-web.sudoers.in の登録内容と完全に一致させること。
        await self._run_checked(
            self._privileged("/usr/bin/systemctl", "--no-block", "restart", _SERVICE_UNIT),
            timeout=10.0,
        )


def _friendly_message(raw: str) -> str:
    """FDX68 のエラーメッセージを、利用者に分かりやすい日本語に置き換える。

    対応表にないものはそのまま返す（情報を失わないため）。
    """
    lowered = raw.lower()
    if "can't connect to emulator" in lowered:
        return "fddemu が起動していません。"
    if "invalid" in lowered and "path" in lowered:
        return "指定されたファイルを開けませんでした。"
    return raw
