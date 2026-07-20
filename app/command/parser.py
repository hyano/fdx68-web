"""FDX68 コマンドの出力パーサー。

実機（FDX68 2.1.0）の出力形式に合わせている。
公式ドキュメントとの差異は docs/fdx68-version-notes.md を参照。
"""

import re

from app.errors import FddemuNotRunning
from app.models.drive import Drive, FDX68Status
from app.models.image import DiskInfo

# fddctl はエラー時でも終了コード 0 を返すことがあるため、
# 終了コードではなく出力中のこの文字列で異常を判定する。
_ERROR_PREFIX = "Error"

# fddemu が起動していないときのメッセージ
_NOT_RUNNING_PATTERN = re.compile(r"can't connect to emulator", re.IGNORECASE)

# 未挿入を表す文字列
_EMPTY_MARKER = "EMPTY"

# 罫線行（+ と - と空白だけで構成される行）
_SEPARATOR_PATTERN = re.compile(r"^[\s+\-|]*$")


def _find_error_line(output: str) -> str | None:
    """出力からエラー行を探す。見つからなければ None。"""
    for line in output.splitlines():
        if line.strip().startswith(_ERROR_PREFIX):
            return line.strip()
    return None


def parse_device_list(output: str) -> FDX68Status:
    """`fddctl -l` の出力を解析する。

    想定する形式::

        ----+----+----+----------------------------------------
         ID | WP | CL | DISK IMAGE
        ----+----+----+----------------------------------------
          0 | ON | 00 | /home/fdx68/fdximg/X68000/disk1.fdx
          1 | -- | 00 | EMPTY
        ----+----+----+----------------------------------------

    fddemu が停止している場合は FddemuNotRunning を送出する。
    """
    error_line = _find_error_line(output)
    if error_line is not None:
        if _NOT_RUNNING_PATTERN.search(error_line):
            raise FddemuNotRunning(detail=error_line)
        raise FddemuNotRunning(
            "FDX68 の状態を取得できませんでした。",
            detail=error_line,
        )

    drives: list[Drive] = []
    for line in output.splitlines():
        drive = _parse_device_line(line)
        if drive is not None:
            drives.append(drive)

    return FDX68Status(fddemu_running=True, drives=drives)


def _parse_device_line(line: str) -> Drive | None:
    """デバイスリストの 1 行を解析する。データ行でなければ None を返す。"""
    if "|" not in line or _SEPARATOR_PATTERN.match(line):
        return None

    # イメージのパスに '|' や空白が含まれていても壊れないよう、
    # 分割回数を 3 に制限して 4 要素目はそれ以上分割しない。
    parts = line.split("|", 3)
    if len(parts) != 4:
        return None

    id_field, wp_field, cl_field, image_field = (p.strip() for p in parts)

    # ヘッダ行（ID | WP | CL | DISK IMAGE）を読み飛ばす
    try:
        drive_id = int(id_field)
    except ValueError:
        return None

    inserted = image_field != _EMPTY_MARKER and image_field != ""
    image = image_field if inserted else None

    # CL は 10 進表記（実機で確認済み）。
    # 将来のバージョンで書式が変わっても、解釈に失敗しただけで監視ループを
    # 止めないよう、None に落として生の文字列を別に保持する。
    try:
        cylinder: int | None = int(cl_field, 10)
    except ValueError:
        cylinder = None

    return Drive(
        id=drive_id,
        inserted=inserted,
        write_protected=wp_field.upper() == "ON",
        cylinder=cylinder,
        cylinder_raw=cl_field,
        image=image,
    )


def check_command_error(output: str) -> str | None:
    """FDX68 コマンドの出力にエラーが含まれていれば、その行を返す。

    fddctl / fdxconv / fdxtool はエラー時でも終了コード 0 を返すことがあるため、
    終了コードとあわせてこの関数の結果も確認すること。
    """
    return _find_error_line(output)


# fdxtool の情報出力から値を取り出すためのパターン。
# 書式はバージョンによって変わりうるため、パースに失敗しても
# 生の出力を DiskInfo.raw_output に残して UI で表示できるようにしている。
_INFO_PATTERNS: dict[str, re.Pattern[str]] = {
    "name": re.compile(r"^\s*(?:disk\s*)?name\s*[:=]\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE),
    "disk_type": re.compile(r"^\s*(?:disk\s*)?type\s*[:=]\s*(\S+)", re.IGNORECASE | re.MULTILINE),
    "rpm": re.compile(r"^\s*rpm\s*[:=]\s*(\d+)", re.IGNORECASE | re.MULTILINE),
    "cylinders": re.compile(r"^\s*cylinders?\s*[:=]\s*(\d+)", re.IGNORECASE | re.MULTILINE),
    "heads": re.compile(r"^\s*heads?\s*[:=]\s*(\d+)", re.IGNORECASE | re.MULTILINE),
    "data_format": re.compile(
        r"^\s*(?:data\s*)?format\s*[:=]\s*(\S+)", re.IGNORECASE | re.MULTILINE
    ),
    "write_protected": re.compile(
        r"^\s*(?:write\s*)?protect\w*\s*[:=]\s*(\S+)", re.IGNORECASE | re.MULTILINE
    ),
}


def parse_disk_info(output: str) -> DiskInfo:
    """`fdxtool FILE` の出力を解析する。

    書式が想定と違っても例外にはせず、取り出せた項目だけを埋めて返す。
    生の出力は常に raw_output に保持する。
    """

    def _match(key: str) -> str | None:
        m = _INFO_PATTERNS[key].search(output)
        return m.group(1).strip() if m else None

    def _match_int(key: str) -> int | None:
        value = _match(key)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    protect_value = _match("write_protected")
    write_protected: bool | None = None
    if protect_value is not None:
        write_protected = protect_value.lower() in {"on", "yes", "true", "1"}

    return DiskInfo(
        name=_match("name"),
        disk_type=_match("disk_type"),
        rpm=_match_int("rpm"),
        cylinders=_match_int("cylinders"),
        heads=_match_int("heads"),
        data_format=_match("data_format"),
        write_protected=write_protected,
        raw_output=output,
    )
