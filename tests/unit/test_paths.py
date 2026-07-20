"""パス検証と名前検証のテスト。

ここが破られるとイメージルートの外を読み書きできてしまうため、
攻撃的な入力を重点的に確認する。
"""

from pathlib import Path

import pytest

from app.errors import InvalidPath
from app.services.paths import (
    parent_of,
    resolve_safe,
    safe_join,
    sanitize_upload_filename,
    to_relative,
    validate_name,
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    images = tmp_path / "fdximg"
    images.mkdir()
    (images / "X68000").mkdir()
    return images


# --- resolve_safe ---------------------------------------------------------


def test_ルート自身は許可される(root: Path):
    assert resolve_safe(root, "") == root.resolve()
    assert resolve_safe(root, ".") == root.resolve()


def test_配下のパスは許可される(root: Path):
    assert resolve_safe(root, "X68000") == (root / "X68000").resolve()


@pytest.mark.parametrize(
    "attack",
    [
        "../etc/passwd",
        "../../etc/passwd",
        "X68000/../../etc",
        "../",
        "..",
    ],
)
def test_親ディレクトリへの脱出は拒否される(root: Path, attack: str):
    with pytest.raises(InvalidPath):
        resolve_safe(root, attack)


@pytest.mark.parametrize("attack", ["/etc/passwd", "/", "//etc"])
def test_絶対パスは拒否される(root: Path, attack: str):
    with pytest.raises(InvalidPath):
        resolve_safe(root, attack)


def test_チルダは拒否される(root: Path):
    with pytest.raises(InvalidPath):
        resolve_safe(root, "~/secret")


def test_NUL文字は拒否される(root: Path):
    with pytest.raises(InvalidPath):
        resolve_safe(root, "disk\x00.fdx")


def test_ルート外を指すシンボリックリンクは拒否される(root: Path, tmp_path: Path):
    """resolve() がリンクを解決するので、リンク経由の脱出も塞げる。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.fdx").write_bytes(b"x")

    (root / "escape").symlink_to(outside)

    with pytest.raises(InvalidPath):
        resolve_safe(root, "escape/secret.fdx")


def test_to_relative(root: Path):
    assert to_relative(root, root) == ""
    assert to_relative(root, root / "X68000" / "a.fdx") == "X68000/a.fdx"


# --- parent_of ------------------------------------------------------------


def test_parent_of():
    assert parent_of("X68000/game/disk1.fdx") == "X68000/game"
    assert parent_of("X68000/disk1.fdx") == "X68000"


def test_ルート直下の親は空文字になる():
    """Path(...).parent は "." を返すが、一覧はルートを空文字で表す。

    表現が 2 つあると、WebSocket の通知を受けたフロントエンドが
    どのノードを更新すべきか判断できなくなる。
    """
    assert parent_of("disk1.fdx") == ""
    assert parent_of("") == ""


# --- validate_name --------------------------------------------------------


def test_通常の名前は許可される():
    assert validate_name("disk1.fdx") == "disk1.fdx"


def test_日本語の名前は許可される():
    """X68000 のソフト名を日本語で管理するため、これは許可する必要がある。"""
    assert validate_name("闇の血族 ディスク1.fdx") == "闇の血族 ディスク1.fdx"


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        ".",
        "..",
        "a/b",
        "a\\b",
        "disk\x00.fdx",
        "disk\n.fdx",
        " leading",
        "trailing ",
        "trailing.",
    ],
)
def test_不正な名前は拒否される(name: str):
    with pytest.raises(InvalidPath):
        validate_name(name)


def test_長すぎる名前は拒否される():
    with pytest.raises(InvalidPath):
        validate_name("あ" * 200)  # UTF-8 で 600 バイト


# --- safe_join ------------------------------------------------------------


def test_safe_join_は結合後もルート配下を確認する(root: Path):
    result = safe_join(root, "X68000", "disk.fdx")
    assert result == (root / "X68000" / "disk.fdx").resolve()


def test_safe_join_は不正な名前を拒否する(root: Path):
    with pytest.raises(InvalidPath):
        safe_join(root, "X68000", "../escape.fdx")


# --- sanitize_upload_filename ---------------------------------------------


def test_相対パス付きのファイル名はベース名に切り詰められる():
    """ブラウザのフォルダドロップでは相対パス付きの名前が送られてくる。"""
    assert sanitize_upload_filename("sub/dir/disk.fdx") == "disk.fdx"
    assert sanitize_upload_filename("../../evil.fdx") == "evil.fdx"
    assert sanitize_upload_filename("C:\\Users\\x\\disk.fdx") == "disk.fdx"


def test_ベース名が不正なら拒否される():
    for name in ["", "..", "sub/..", "/"]:
        with pytest.raises(InvalidPath):
            sanitize_upload_filename(name)


def test_日本語のファイル名は保持される():
    assert sanitize_upload_filename("ゲーム/ディスク1.fdx") == "ディスク1.fdx"
