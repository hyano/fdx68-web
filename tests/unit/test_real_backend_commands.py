"""RealBackend が組み立てるコマンドのテスト。

実際に FDX68 を呼ばず、FakeCommandRunner に渡された引数だけを検証する。

**権限の境界を固定するためのテストである。** どのコマンドを昇格して実行するかは
セキュリティ上の判断なので、意図せず変わったら気付けるようにしておく。
"""

from pathlib import Path

import pytest

from app.backends.real import RealFDX68Backend
from app.command.runner import CommandResult, FakeCommandRunner
from app.config import Settings
from app.errors import CommandFailed

DEVICE_LIST = """\
 ID | WP | CL | DISK IMAGE
  0 | -- | 00 | EMPTY
  1 | -- | 00 | EMPTY
"""


#: pgrep が「該当なし」を返すときの結果（fddemu は停止中）
NOT_FOUND = CommandResult(args=[], returncode=1, stdout="", stderr="")


@pytest.fixture
def runner() -> FakeCommandRunner:
    fake = FakeCommandRunner()
    fake.default_result = CommandResult(args=[], returncode=0, stdout=DEVICE_LIST, stderr="")
    # 既定では fddemu は停止しているものとして扱う。
    # これを設定しないと、pgrep にも既定の応答が返って「起動中」に見えてしまう。
    fake.responses[("pgrep", "-x", "fddemu")] = NOT_FOUND
    return fake


@pytest.fixture
def backend(runner: FakeCommandRunner) -> RealFDX68Backend:
    settings = Settings(backend="real", bin_dir=Path("/usr/local/bin"), use_sudo=True)
    return RealFDX68Backend(settings, runner)


async def test_fddctl_は_sudo_を経由しない(backend: RealFDX68Backend, runner: FakeCommandRunner):
    """fddctl は root 権限を必要としない（実機で確認済み）。

    2 秒ごとに実行されるため、不要な昇格を常態化させない。
    """
    await backend.get_status()

    args = runner.calls[0]
    assert args[0] != "sudo"
    assert args[0] == "/usr/local/bin/fddctl"
    assert args[1] == "-l"


async def test_ドライブ操作も_sudo_を経由しない(
    backend: RealFDX68Backend, runner: FakeCommandRunner
):
    await backend.insert(0, Path("/home/pi/fdximg/disk.fdx"))

    args = runner.calls[-1]
    assert "sudo" not in args
    assert args == [
        "/usr/local/bin/fddctl",
        "-i",
        "0",
        "-c",
        "insert",
        "/home/pi/fdximg/disk.fdx",
    ]


async def test_fddemu_は_sudo_を経由する(backend: RealFDX68Backend, runner: FakeCommandRunner):
    """fddemu は /dev/mem を使うため root 権限が必須。"""
    await backend.start_fddemu()

    args = runner.spawned[0]
    assert args[:2] == ["sudo", "-n"]
    assert args[2] == "/usr/local/bin/fddemu"


async def test_reboot_と_poweroff_は_sudo_を経由する(
    backend: RealFDX68Backend, runner: FakeCommandRunner
):
    await backend.reboot()
    assert runner.spawned[-1][:2] == ["sudo", "-n"]

    await backend.poweroff()
    assert runner.spawned[-1][:2] == ["sudo", "-n"]


async def test_サービス再起動の引数(backend: RealFDX68Backend, runner: FakeCommandRunner):
    """sudoers の登録内容と完全に一致していないと実機で弾かれるため、全引数を固定する。

    packaging/fdx68-web.sudoers.in の systemctl の行と対応している。
    --no-block を落とすと、自分自身の停止を待って応答を返せなくなる。
    """
    await backend.restart_service()

    assert runner.calls[-1] == [
        "sudo",
        "-n",
        "/usr/bin/systemctl",
        "--no-block",
        "restart",
        "fdx68-web.service",
    ]
    # 停止シグナルで殺されうるため spawn は使わない
    assert runner.spawned == []


async def test_use_sudo_が_false_なら昇格しない(runner: FakeCommandRunner):
    """アプリ自体を root で動かす場合に使う。"""
    settings = Settings(backend="real", bin_dir=Path("/usr/local/bin"), use_sudo=False)
    backend = RealFDX68Backend(settings, runner)

    await backend.start_fddemu()
    assert runner.spawned[0][0] == "/usr/local/bin/fddemu"

    await backend.restart_service()
    assert runner.calls[-1][0] == "/usr/bin/systemctl"


#: fddctl -l が「fddemu が疎通できない」ときに返す出力
_CONNECT_ERROR = CommandResult(
    args=[], returncode=0, stdout="Error: can't connect to emulator\n", stderr=""
)

#: pgrep が「fddemu が生存している」ときに返す出力
_ALIVE = CommandResult(args=["pgrep", "-x", "fddemu"], returncode=0, stdout="1234\n", stderr="")


async def test_起動確認が遅延しても成功する(
    backend: RealFDX68Backend, runner: FakeCommandRunner, monkeypatch: pytest.MonkeyPatch
):
    """疎通確認が数回失敗しても、プロセスが生存していればポーリングで成功する。

    実機（Pi 3 A+）ではメモリが逼迫しており、疎通まで 1 秒を超えることがある。
    固定 1 回待ちだと誤って「起動できませんでした」になっていた不具合の回帰テスト。
    """
    monkeypatch.setattr("app.backends.real._STARTUP_TIMEOUT", 1.0)
    monkeypatch.setattr("app.backends.real._POLL_INTERVAL", 0.01)

    # 起動前チェックでは未起動、以降は生存している状態を返す
    runner.sequences[("pgrep", "-x", "fddemu")] = [NOT_FOUND]
    runner.responses[("pgrep", "-x", "fddemu")] = _ALIVE

    # 疎通確認は 2 回失敗させたあと、runner.default_result (DEVICE_LIST) で成功させる
    runner.sequences[("/usr/local/bin/fddctl", "-l")] = [_CONNECT_ERROR, _CONNECT_ERROR]

    await backend.start_fddemu()  # 例外が出なければ成功


async def test_起動直後にプロセスが消えたら失敗する(
    backend: RealFDX68Backend, runner: FakeCommandRunner, monkeypatch: pytest.MonkeyPatch
):
    """疎通確認に失敗し、かつプロセスも生きていない場合のみ本当の起動失敗とみなす。"""
    monkeypatch.setattr("app.backends.real._STARTUP_TIMEOUT", 1.0)
    monkeypatch.setattr("app.backends.real._POLL_INTERVAL", 0.01)

    runner.default_result = _CONNECT_ERROR
    # pgrep は fixture 既定のまま NOT_FOUND（= プロセスは生きていない）

    with pytest.raises(CommandFailed):
        await backend.start_fddemu()


async def test_起動確認がタイムアウトしてもプロセスが生きていれば成功する(
    backend: RealFDX68Backend, runner: FakeCommandRunner, monkeypatch: pytest.MonkeyPatch
):
    """疎通確認が最後まで失敗しても、プロセスが生存していれば誤報にしない。

    Web UI は起動直後の 1 回のレスポンスだけでなく、その後の状態監視ループ
    (`fddctl -l` のポーリング) で実際の状態に追従する。
    """
    monkeypatch.setattr("app.backends.real._STARTUP_TIMEOUT", 0.05)
    monkeypatch.setattr("app.backends.real._POLL_INTERVAL", 0.01)

    runner.sequences[("pgrep", "-x", "fddemu")] = [NOT_FOUND]
    runner.responses[("pgrep", "-x", "fddemu")] = _ALIVE
    runner.default_result = _CONNECT_ERROR

    await backend.start_fddemu()  # 例外が出なければ成功


async def test_fdxconv_の引数(backend: RealFDX68Backend, runner: FakeCommandRunner):
    """変換は元ファイルを変更しないよう、入力と出力を明示的に指定する。"""
    await backend.convert_to_fdx(Path("/img/a.d88"), Path("/img/a.fdx"))

    args = runner.calls[-1]
    assert "sudo" not in args
    assert args[0] == "/usr/local/bin/fdxconv"
    assert args[args.index("-i") + 1] == "/img/a.d88"
    assert args[args.index("-o") + 1] == "/img/a.fdx"
    # X68000 では既定の upd765 / encode が正しい
    assert args[args.index("-a") + 1] == "upd765"
    assert args[args.index("-f") + 1] == "encode"


async def test_ブランクイメージ作成の引数(backend: RealFDX68Backend, runner: FakeCommandRunner):
    await backend.create_blank_image(Path("/img/new.fdx"), disk_name="TEST")

    args = runner.calls[-1]
    assert args[0] == "/usr/local/bin/fdxtool"
    assert args[1] == "-c"
    assert args[args.index("-t") + 1] == "2HD"
    assert args[args.index("-n") + 1] == "TEST"
    # RPM は指定しない。FDX68 の既定値（2HD なら 360）が X68000 にとって正しい。
    assert "-r" not in args
    assert args[-1] == "/img/new.fdx"


def _device_list(wp0: str) -> str:
    return f" ID | WP | CL | DISK IMAGE\n  0 | {wp0} | 00 | /img/a.fdx\n  1 | -- | 00 | EMPTY\n"


async def test_プロテクトは希望と同じ状態なら実行しない(runner: FakeCommandRunner):
    """`fddctl -c protect` はトグルなので、状態を確認せず実行してはいけない。

    既に希望どおりの状態のときに実行すると、実機のライトプロテクトが逆になる。
    """
    settings = Settings(backend="real", bin_dir=Path("/usr/local/bin"), use_sudo=True)
    backend = RealFDX68Backend(settings, runner)

    # 既にプロテクトが ON の状態
    runner.default_result = CommandResult(
        args=[], returncode=0, stdout=_device_list("ON"), stderr=""
    )

    await backend.set_write_protect(0, True)

    protect_calls = [c for c in runner.calls if "protect" in c]
    assert protect_calls == [], "同じ状態なのにトグルを実行している"


async def test_プロテクトは希望と違う状態なら実行する(runner: FakeCommandRunner):
    settings = Settings(backend="real", bin_dir=Path("/usr/local/bin"), use_sudo=True)
    backend = RealFDX68Backend(settings, runner)

    # 現在はプロテクト OFF（--）なので、ON にするには反転が必要
    runner.default_result = CommandResult(
        args=[], returncode=0, stdout=_device_list("--"), stderr=""
    )

    await backend.set_write_protect(0, True)

    protect_calls = [c for c in runner.calls if "protect" in c]
    assert protect_calls == [["/usr/local/bin/fddctl", "-i", "0", "-c", "protect"]]


async def test_停止は_fddctl_stop_を先に試す(runner: FakeCommandRunner):
    """通常は --stop だけで止まる（実機で確認済み）。

    正常時に pkill へ進まないことを確認する。
    エミュレーション中の突然死を避けるため、いきなり kill しない。
    """
    settings = Settings(backend="real", bin_dir=Path("/usr/local/bin"), use_sudo=True)
    backend = RealFDX68Backend(settings, runner)

    await backend.stop_fddemu()

    assert runner.calls[0] == ["/usr/local/bin/fddctl", "--stop"]
    assert not [c for c in runner.calls if "pkill" in c], "正常時に pkill を呼んでいる"


async def test_pkill_は完全一致で呼ぶ(runner: FakeCommandRunner, monkeypatch: pytest.MonkeyPatch):
    """-x を付けないと fddemu を含む別プロセスを巻き込む恐れがある。"""
    monkeypatch.setattr("app.backends.real._STOP_TIMEOUT", 0.05)
    monkeypatch.setattr("app.backends.real._POLL_INTERVAL", 0.01)

    settings = Settings(backend="real", bin_dir=Path("/usr/local/bin"), use_sudo=True)
    backend = RealFDX68Backend(settings, runner)

    # fddctl --stop の後も動いたままに見せて、pkill へのフォールバックを発生させる
    runner.responses[("pgrep", "-x", "fddemu")] = _ALIVE

    with pytest.raises(Exception):  # noqa: B017  最終的に停止できず失敗する
        await backend.stop_fddemu()

    pkill_calls = [c for c in runner.calls if "pkill" in c]
    assert pkill_calls, "pkill へフォールバックしていない"
    for call in pkill_calls:
        assert "-x" in call, f"完全一致 (-x) が指定されていない: {call}"
        assert call[:2] == ["sudo", "-n"]


async def test_停止確認が遅延しても_pkill_に落ちない(
    runner: FakeCommandRunner, monkeypatch: pytest.MonkeyPatch
):
    """fddctl --stop 後、消滅確認が数回遅れても、期限内に消えれば pkill へ進まない。

    メモリ逼迫下で正常に終了処理中の fddemu を pkill しないための回帰テスト。
    """
    monkeypatch.setattr("app.backends.real._STOP_TIMEOUT", 1.0)
    monkeypatch.setattr("app.backends.real._POLL_INTERVAL", 0.01)

    settings = Settings(backend="real", bin_dir=Path("/usr/local/bin"), use_sudo=True)
    backend = RealFDX68Backend(settings, runner)

    runner.sequences[("pgrep", "-x", "fddemu")] = [_ALIVE, _ALIVE, NOT_FOUND]

    await backend.stop_fddemu()

    assert not [c for c in runner.calls if "pkill" in c], "早期に消えたのに pkill している"
