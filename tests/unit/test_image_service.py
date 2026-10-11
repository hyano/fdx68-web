"""ファイル種別判定・並び順・複製名の生成のテスト。"""

from pathlib import Path

from app.models.image import ImageEntry, ImageKind
from app.services.image_service import (
    ImageService,
    classify,
    entry_sort_key,
    natural_sort_key,
)


def test_拡張子から種別を判定する(tmp_path: Path):
    (tmp_path / "d").mkdir()
    for name in ["a.fdx", "b.d88", "c.txt"]:
        (tmp_path / name).write_bytes(b"")

    assert classify(tmp_path / "d") is ImageKind.DIRECTORY
    assert classify(tmp_path / "a.fdx") is ImageKind.FDX
    assert classify(tmp_path / "b.d88") is ImageKind.CONVERTIBLE_IMAGE
    assert classify(tmp_path / "c.txt") is ImageKind.UNSUPPORTED


def test_拡張子は大文字小文字を区別しない(tmp_path: Path):
    for name in ["A.FDX", "B.D88", "c.Xdf"]:
        (tmp_path / name).write_bytes(b"")

    assert classify(tmp_path / "A.FDX") is ImageKind.FDX
    assert classify(tmp_path / "B.D88") is ImageKind.CONVERTIBLE_IMAGE
    assert classify(tmp_path / "c.Xdf") is ImageKind.CONVERTIBLE_IMAGE


def test_自然順ソート():
    """X68000 のソフトは複数枚組で disk1..disk10 の命名が頻出する。

    辞書順だと disk1, disk10, disk2 になってしまい実用上かなり不便になる。
    """
    names = ["disk10.fdx", "disk2.fdx", "disk1.fdx"]
    assert sorted(names, key=natural_sort_key) == [
        "disk1.fdx",
        "disk2.fdx",
        "disk10.fdx",
    ]


def test_ディレクトリが先に並ぶ():
    entries = [
        ImageEntry(name="b.fdx", path="b.fdx", kind=ImageKind.FDX),
        ImageEntry(name="a_dir", path="a_dir", kind=ImageKind.DIRECTORY),
        ImageEntry(name="a.fdx", path="a.fdx", kind=ImageKind.FDX),
        ImageEntry(name="z_dir", path="z_dir", kind=ImageKind.DIRECTORY),
    ]
    ordered = [e.name for e in sorted(entries, key=entry_sort_key)]
    assert ordered == ["a_dir", "z_dir", "a.fdx", "b.fdx"]


def test_複製名は連番で生成される(tmp_path: Path):
    source = tmp_path / "disk.fdx"
    source.write_bytes(b"")

    first = ImageService._next_copy_name(source)
    assert first.name == "disk copy.fdx"

    first.write_bytes(b"")
    second = ImageService._next_copy_name(source)
    assert second.name == "disk copy 2.fdx"

    second.write_bytes(b"")
    third = ImageService._next_copy_name(source)
    assert third.name == "disk copy 3.fdx"


def test_変換先の衝突判定は拡張子の大文字小文字を区別しない(tmp_path: Path):
    (tmp_path / "GAME.FDX").write_bytes(b"")

    found = ImageService._find_existing_fdx(tmp_path / "GAME.fdx")
    assert found is not None
    assert found.name == "GAME.FDX"


def test_変換先と衝突しないFDXは無視する(tmp_path: Path):
    (tmp_path / "other.fdx").write_bytes(b"")
    (tmp_path / "game.d88").write_bytes(b"")

    assert ImageService._find_existing_fdx(tmp_path / "game.fdx") is None
