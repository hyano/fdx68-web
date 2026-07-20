"""fddctl / fdxtool の出力パーサーのテスト。

入力は実機（FDX68 2.1.0）の出力形式に合わせている。
"""

import pytest

from app.command.parser import check_command_error, parse_device_list, parse_disk_info
from app.errors import FddemuNotRunning

# 実機の出力そのまま
DEVICE_LIST = """\
----+----+----+-------------------------------------------------
 ID | WP | CL | DISK IMAGE
----+----+----+-------------------------------------------------
  0 | ON | 00 | /home/fdx68/fdximg/X68000/yamikets/yamiketsu1.fdx
  1 | ON | 00 | /home/fdx68/fdximg/X68000/yamikets/yamiketsu2.fdx
----+----+----+-------------------------------------------------
"""

DEVICE_LIST_EMPTY = """\
----+----+----+-------------------------------------------------
 ID | WP | CL | DISK IMAGE
----+----+----+-------------------------------------------------
  0 | -- | 00 | EMPTY
  1 | ON | 00 | yamiketsu2.fdx
----+----+----+-------------------------------------------------
"""

NOT_RUNNING = "Error : Can't connect to emulator process\n"


def test_両方のドライブが解析される():
    status = parse_device_list(DEVICE_LIST)

    assert status.fddemu_running is True
    assert len(status.drives) == 2
    assert status.drives[0].id == 0
    assert status.drives[0].inserted is True
    assert status.drives[0].write_protected is True
    assert status.drives[0].cylinder == 0
    assert status.drives[0].image == "/home/fdx68/fdximg/X68000/yamikets/yamiketsu1.fdx"


def test_EMPTY_は未挿入として扱われる():
    status = parse_device_list(DEVICE_LIST_EMPTY)

    assert status.drives[0].inserted is False
    assert status.drives[0].image is None
    assert status.drives[0].write_protected is False

    assert status.drives[1].inserted is True
    assert status.drives[1].image == "yamiketsu2.fdx"


def test_ライトプロテクトのONとダッシュを判定する():
    status = parse_device_list(DEVICE_LIST_EMPTY)
    assert status.drives[0].write_protected is False  # --
    assert status.drives[1].write_protected is True  # ON


def test_パスに空白が含まれても壊れない():
    """split の分割回数を制限していないと、空白でパスが切れてしまう。"""
    output = """\
----+----+----+------------------------------------------
 ID | WP | CL | DISK IMAGE
----+----+----+------------------------------------------
  0 | -- | 00 | /home/fdx68/fdximg/Disk Set 1/disk 1.fdx
----+----+----+------------------------------------------
"""
    status = parse_device_list(output)
    assert status.drives[0].image == "/home/fdx68/fdximg/Disk Set 1/disk 1.fdx"


def test_パスにパイプ記号が含まれても壊れない():
    """4 要素目はそれ以上分割しないので、パス中の | は保持される。"""
    output = """\
 ID | WP | CL | DISK IMAGE
  0 | -- | 00 | /home/fdx68/fdximg/a|b/disk.fdx
"""
    status = parse_device_list(output)
    assert status.drives[0].image == "/home/fdx68/fdximg/a|b/disk.fdx"


def test_日本語のパスが扱える():
    """X68000 のソフトはディレクトリ名を日本語で管理することが多い。"""
    output = """\
 ID | WP | CL | DISK IMAGE
  0 | ON | 00 | /home/fdx68/fdximg/ゲーム/闇の血族/ディスク1.fdx
"""
    status = parse_device_list(output)
    assert status.drives[0].image == "/home/fdx68/fdximg/ゲーム/闇の血族/ディスク1.fdx"


def test_大文字の拡張子も挿入として扱われる():
    output = """\
 ID | WP | CL | DISK IMAGE
  0 | ON | 00 | /home/fdx68/fdximg/DISK.FDX
"""
    status = parse_device_list(output)
    assert status.drives[0].inserted is True
    assert status.drives[0].image == "/home/fdx68/fdximg/DISK.FDX"


def test_fddemu_停止時は例外になる():
    with pytest.raises(FddemuNotRunning):
        parse_device_list(NOT_RUNNING)


def test_シリンダが数値なら整数になる():
    output = """\
 ID | WP | CL | DISK IMAGE
  0 | ON | 42 | /home/fdx68/fdximg/disk.fdx
"""
    status = parse_device_list(output)
    assert status.drives[0].cylinder == 42
    assert status.drives[0].cylinder_raw == "42"


def test_シリンダは10進で解釈される():
    """CL は 10 進表記（実機で確認済み）。

    16 進として解釈すると 10 が 16、77 が 119 になり、
    X68000 の 2HD（77 シリンダ）では実際に誤差が出る。
    """
    output = """\
 ID | WP | CL | DISK IMAGE
  0 | ON | 10 | /home/fdx68/fdximg/disk.fdx
  1 | ON | 77 | /home/fdx68/fdximg/disk2.fdx
"""
    status = parse_device_list(output)
    assert status.drives[0].cylinder == 10
    assert status.drives[1].cylinder == 77


def test_シリンダが解釈できなくても監視を止めない():
    """将来のバージョンで書式が変わっても、例外にせず生の文字列を保持する。

    状態監視は 2 秒ごとに動き続けるため、1 回の解釈失敗で止めない。
    """
    output = """\
 ID | WP | CL | DISK IMAGE
  0 | ON | ?? | /home/fdx68/fdximg/disk.fdx
"""
    status = parse_device_list(output)
    assert status.drives[0].cylinder is None
    assert status.drives[0].cylinder_raw == "??"
    # 解釈に失敗してもドライブ自体の情報は失われない
    assert status.drives[0].inserted is True


def test_ヘッダ行と罫線行は読み飛ばされる():
    status = parse_device_list(DEVICE_LIST)
    assert all(drive.id in (0, 1) for drive in status.drives)


def test_エラー行の検出():
    assert check_command_error(NOT_RUNNING) is not None
    assert check_command_error("Error : Invalid source image file path") is not None
    assert check_command_error(DEVICE_LIST) is None
    assert check_command_error("") is None


# --- fdxtool -------------------------------------------------------------


def test_ディスク情報を解析できる():
    output = """\
Disk Name : YAMIKETSU 1
Disk Type : 2HD
RPM : 360
Cylinders : 77
Heads : 2
Format : encode
Protect : on
"""
    info = parse_disk_info(output)

    assert info.name == "YAMIKETSU 1"
    assert info.disk_type == "2HD"
    assert info.rpm == 360
    assert info.cylinders == 77
    assert info.heads == 2
    assert info.data_format == "encode"
    assert info.write_protected is True


def test_解析できなくても生の出力を保持する():
    """FDX68 のバージョン差で書式が変わっても情報を失わないため。"""
    output = "まったく想定外の出力\n"
    info = parse_disk_info(output)

    assert info.name is None
    assert info.rpm is None
    assert info.raw_output == output
