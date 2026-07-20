"""パスと名前の検証。

Web UI から受け取ったパスをファイルシステム上のパスに変換する唯一の経路。
**ここを通さずにクライアント由来の文字列でファイル操作をしないこと。**
"""

import unicodedata
from pathlib import Path, PurePosixPath

from app.errors import InvalidPath

#: ファイル名の最大長（バイト数）。多くのファイルシステムの上限に合わせている。
MAX_NAME_BYTES = 255


def resolve_safe(root: Path, relative: str | None) -> Path:
    """イメージルートからの相対パスを絶対パスに変換する。

    ルートの外を指すパスはすべて拒否する。

    `Path.resolve()` はシンボリックリンクも解決するため、
    ルート外を指すシンボリックリンク経由の脱出も同時に塞げる。
    """
    rel = (relative or "").strip()

    # クライアントから絶対パスは受け取らない
    if rel.startswith("/") or PurePosixPath(rel).is_absolute():
        raise InvalidPath(detail=f"絶対パスが指定されました: {rel!r}")

    # ~ の展開を期待させない
    if rel.startswith("~"):
        raise InvalidPath(detail=f"~ を含むパスが指定されました: {rel!r}")

    if "\x00" in rel:
        raise InvalidPath(detail="NUL 文字が含まれています")

    root_resolved = root.resolve()
    target = (root_resolved / rel).resolve()

    if target != root_resolved and root_resolved not in target.parents:
        raise InvalidPath(detail=f"ルート外を指しています: {rel!r} -> {target}")

    return target


def to_relative(root: Path, target: Path) -> str:
    """絶対パスをイメージルートからの相対パスに変換する。

    ルート自身の場合は空文字を返す。
    """
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if target_resolved == root_resolved:
        return ""
    return str(target_resolved.relative_to(root_resolved))


def is_within(root: Path, target: Path) -> bool:
    """target が root の配下（または root 自身）にあるかを返す。"""
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    return target_resolved == root_resolved or root_resolved in target_resolved.parents


def validate_name(name: str) -> str:
    """新規作成・リネームで使う名前を検証する。

    受け取るのは**パスではなく単一の名前**である。
    日本語などの Unicode 文字は許可する（X68000 のソフト名を日本語で管理するため）。
    """
    if name is None:
        raise InvalidPath("名前が指定されていません。")

    # 正規化しておかないと、見た目が同じでバイト列が異なる名前が混在する
    normalized = unicodedata.normalize("NFC", name)

    if normalized != normalized.strip():
        raise InvalidPath("名前の先頭と末尾に空白は使えません。")

    if not normalized:
        raise InvalidPath("名前が空です。")

    if len(normalized.encode("utf-8")) > MAX_NAME_BYTES:
        raise InvalidPath(f"名前が長すぎます（{MAX_NAME_BYTES} バイトまで）。")

    if "/" in normalized or "\\" in normalized:
        raise InvalidPath("名前にパス区切り文字は使えません。")

    if normalized in {".", ".."}:
        raise InvalidPath("その名前は使えません。")

    if normalized.startswith(".") and normalized.endswith("."):
        # 先頭のドットは隠しファイルとして許容するが、末尾のドットは許可しない
        raise InvalidPath("名前の末尾にドットは使えません。")

    if normalized.endswith("."):
        raise InvalidPath("名前の末尾にドットは使えません。")

    # 制御文字（NUL を含む）を拒否する
    if any(unicodedata.category(ch) == "Cc" for ch in normalized):
        raise InvalidPath("名前に制御文字は使えません。")

    return normalized


def safe_join(root: Path, parent_relative: str | None, name: str) -> Path:
    """親ディレクトリと名前を結合し、結果がルート配下にあることを再確認する。

    名前の検証を通していても、結合後にもう一度確認する（多層防御）。
    """
    parent = resolve_safe(root, parent_relative)
    validated = validate_name(name)
    target = (parent / validated).resolve()

    if not is_within(root, target):
        raise InvalidPath(detail=f"結合結果がルート外を指しています: {target}")

    return target


def sanitize_upload_filename(filename: str) -> str:
    """アップロードされたファイル名を安全な名前に変換する。

    ブラウザからフォルダをドロップした場合、`sub/dir/disk.fdx` のように
    相対パス付きのファイル名が送られてくることがある。
    そのまま結合するとイメージルートの外に書き出せてしまうため、
    **必ずベース名だけを取り出す。**
    """
    if not filename:
        raise InvalidPath("ファイル名がありません。")

    # Windows 由来の区切り文字も潰してからベース名を取る
    normalized = filename.replace("\\", "/")
    base = PurePosixPath(normalized).name

    if not base or base in {".", ".."}:
        raise InvalidPath(f"不正なファイル名です: {filename!r}")

    return validate_name(base)
