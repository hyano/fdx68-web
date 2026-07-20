"""Mock バックエンドのディスク情報の扱いのテスト。

**mock は FDX68 の出力書式に依存してはならない。**
以前は fdxtool の出力を模したテキストを書いて本物のパーサーで読み戻していたため、
実機側の書式が変わると mock とテストのフィクスチャが道連れで壊れる状態だった。
ここでは mock が自分の形式だけで完結していることを固定する。
"""

from pathlib import Path

import pytest

from app.backends.mock import MockFDX68Backend
from app.errors import FddemuNotRunning, InvalidParameter, NotFound
from app.models.image import DataFormat, DiskType


@pytest.fixture
def backend() -> MockFDX68Backend:
    return MockFDX68Backend()


# --- ディスク情報 -----------------------------------------------------------


async def test_作成したイメージの情報を読み戻せる(backend: MockFDX68Backend, tmp_path: Path):
    target = tmp_path / "disk.fdx"

    await backend.create_blank_image(
        target,
        disk_type=DiskType.TWO_HD,
        disk_name="テストディスク",
        write_protected=True,
    )
    info = await backend.get_disk_info(target)

    assert info.name == "テストディスク"
    assert info.disk_type == "2HD"
    assert info.write_protected is True
    # X68000 で使う 2HD は 360rpm
    assert info.rpm == 360


async def test_属性の変更は指定した項目だけを書き換える(backend: MockFDX68Backend, tmp_path: Path):
    """ディスク名だけを変えたときに、プロテクト属性が巻き添えで消えては困る。"""
    target = tmp_path / "disk.fdx"
    await backend.create_blank_image(target, disk_name="変更前", write_protected=True)

    await backend.set_disk_attributes(target, disk_name="変更後")
    info = await backend.get_disk_info(target)

    assert info.name == "変更後"
    assert info.write_protected is True


async def test_mock_形式でないファイルは生の内容だけを返す(
    backend: MockFDX68Backend, tmp_path: Path
):
    """解析できなかった実機と同じ扱いにする。情報を失わないよう生の内容は残す。"""
    target = tmp_path / "unknown.fdx"
    target.write_bytes("これは mock の形式ではない".encode())

    info = await backend.get_disk_info(target)

    assert info.name is None
    assert info.raw_output == "これは mock の形式ではない"


async def test_mock_形式が壊れていても例外にしない(backend: MockFDX68Backend, tmp_path: Path):
    target = tmp_path / "broken.fdx"
    target.write_bytes("FDX68-MOCK-IMAGE\n{壊れた JSON".encode())

    info = await backend.get_disk_info(target)

    assert info.name is None
    assert info.raw_output


async def test_変換で作られるのも_mock_形式(backend: MockFDX68Backend, tmp_path: Path):
    """変換結果に対して続けて情報取得ができる必要がある。"""
    source = tmp_path / "source.d88"
    source.write_bytes(b"D88-DUMMY")
    destination = tmp_path / "source.fdx"

    await backend.convert_to_fdx(source, destination, data_format=DataFormat.RAW)
    info = await backend.get_disk_info(destination)

    assert info.name == "source"
    assert info.data_format == "raw"
    # 元ファイルは変更しない（実機と同じ）
    assert source.read_bytes() == b"D88-DUMMY"


async def test_存在しないファイルは_NotFound(backend: MockFDX68Backend, tmp_path: Path):
    with pytest.raises(NotFound):
        await backend.get_disk_info(tmp_path / "missing.fdx")


# --- 例外の種類を Real と揃える ---------------------------------------------


async def test_fddemu_停止中の操作は_FddemuNotRunning(backend: MockFDX68Backend):
    """CommandFailed(500) を返していると、mock で通ったテストが実機で 409 になる。"""
    with pytest.raises(FddemuNotRunning):
        await backend.eject(0)


async def test_存在しないドライブは_InvalidParameter(backend: MockFDX68Backend):
    backend.fddemu_running = True

    with pytest.raises(InvalidParameter):
        await backend.eject(9)
