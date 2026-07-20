"""ディスクイメージの管理。

**ディスクイメージは代替不能な資産である。**
このモジュールのガード条件は、それを壊さないためにある。緩めないこと。
"""

import asyncio
import logging
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from app.backends.base import FDX68Backend
from app.config import Settings
from app.errors import (
    AlreadyExists,
    DirectoryNotEmpty,
    ImageMounted,
    InsufficientSpace,
    InvalidPath,
    NotFound,
    UnsupportedFileType,
    UploadTooLarge,
)
from app.models.image import (
    CONVERTIBLE_EXTENSIONS,
    FDX_EXTENSION,
    UPLOADABLE_EXTENSIONS,
    AnalyzeMode,
    DataFormat,
    DiskInfo,
    DiskType,
    ImageEntry,
    ImageKind,
    ImageListing,
)
from app.services import paths as path_utils

logger = logging.getLogger(__name__)

#: 書き込み中の一時ファイルに付ける拡張子。
#: 途中まで書けたディスクイメージを .fdx という名前で存在させないため。
PART_SUFFIX = ".part"

#: アップロード時に一度に読むバイト数。メモリ使用量を一定に保つ。
UPLOAD_CHUNK_SIZE = 1024 * 1024

#: 自然順ソート用（数字部分を数値として比較する）
_NATURAL_SORT_PATTERN = re.compile(r"(\d+)")


class ChunkReader(Protocol):
    """チャンク単位で読み出せるオブジェクト。

    FastAPI の `UploadFile` がこれを満たす。
    サービス層が FastAPI に依存しないよう、具象型ではなく振る舞いで受ける。
    """

    async def read(self, size: int) -> bytes: ...


def classify(path: Path) -> ImageKind:
    """ファイルの種別を判定する。拡張子は大文字小文字を区別しない。"""
    if path.is_dir():
        return ImageKind.DIRECTORY

    suffix = path.suffix.lower()
    if suffix == FDX_EXTENSION:
        return ImageKind.FDX
    if suffix in CONVERTIBLE_EXTENSIONS:
        return ImageKind.CONVERTIBLE_IMAGE
    return ImageKind.UNSUPPORTED


def natural_sort_key(name: str) -> tuple[object, ...]:
    """自然順ソートのキーを返す。

    `disk1, disk2, disk10` が辞書順で `disk1, disk10, disk2` にならないようにする。
    X68000 のソフトは複数枚組でこの命名が頻出するため、実用上重要。
    """
    parts = _NATURAL_SORT_PATTERN.split(name.lower())
    key: list[object] = []
    for index, part in enumerate(parts):
        # split の結果は「文字列, 数字, 文字列, 数字, ...」と交互になる
        key.append(int(part) if index % 2 == 1 else part)
    return tuple(key)


def entry_sort_key(entry: ImageEntry) -> tuple[int, tuple[object, ...]]:
    """ディレクトリを先に、その中では自然順で並べる。"""
    is_dir = 0 if entry.kind is ImageKind.DIRECTORY else 1
    return (is_dir, natural_sort_key(entry.name))


class ImageService:
    """ディスクイメージのファイル操作。"""

    def __init__(self, settings: Settings, backend: FDX68Backend) -> None:
        self._settings = settings
        self._backend = backend

    @property
    def root(self) -> Path:
        return self._settings.image_dir

    # --- パスの解決 ---------------------------------------------------------

    def resolve(self, relative: str | None) -> Path:
        """相対パスを絶対パスに変換する（ルート外は拒否）。"""
        return path_utils.resolve_safe(self.root, relative)

    def to_relative(self, absolute: Path) -> str:
        return path_utils.to_relative(self.root, absolute)

    # --- ガード -------------------------------------------------------------
    #
    # 各操作の前置き検査をここに集約する。
    # ガード条件が分散すると、新しい操作を追加したときに検査を入れ忘れて
    # 挿入中のイメージを壊す事故につながる。**条件は緩めないこと。**

    def _require_existing(self, relative: str | None) -> Path:
        """相対パスを解決し、実在することを確認して返す。

        外部（SSH や rsync）で削除されている場合があるため、
        すべての操作がこの検査を通る。
        """
        target = self.resolve(relative)
        if not target.exists():
            raise NotFound()
        return target

    def _reject_root(self, target: Path, action: str) -> None:
        """ルートフォルダ自身への破壊的操作を拒否する。"""
        if target == self.root.resolve():
            raise InvalidPath(f"ルートフォルダは{action}できません。")

    @staticmethod
    def _require_fdx(target: Path) -> None:
        """FDX 形式であることを確認する。

        fdxtool は FDX しか扱えないため、情報取得と属性変更の前に必要。
        """
        if classify(target) is not ImageKind.FDX:
            raise UnsupportedFileType("FDX 形式のファイルではありません。")

    # --- 挿入中イメージのガード ---------------------------------------------

    async def mounted_paths(self) -> dict[Path, list[int]]:
        """現在挿入されているイメージの絶対パスと、そのドライブ番号を返す。"""
        status = await self._backend.get_status()
        mounted: dict[Path, list[int]] = {}
        for drive in status.drives:
            if not drive.image:
                continue
            try:
                key = Path(drive.image).resolve()
            except OSError:
                # 外部で削除された直後などに解決できないことがある
                continue
            mounted.setdefault(key, []).append(drive.id)
        return mounted

    async def assert_not_mounted(self, target: Path) -> None:
        """対象が挿入中でないことを確認する。挿入中なら例外を送出する。

        対象がディレクトリの場合、その配下に挿入中のイメージがあっても拒否する
        （親フォルダを動かすと配下のパスがまとめて変わるため）。

        削除・リネーム・移動・ディスク属性編集の 4 箇所から呼ばれる。
        新しい破壊的操作を追加したときは、必ずここを通すこと。
        """
        mounted = await self.mounted_paths()
        if not mounted:
            return

        try:
            target_resolved = target.resolve()
        except OSError:
            return

        for mounted_path, drive_ids in mounted.items():
            if mounted_path == target_resolved:
                drives = " と ".join(f"Drive {i}" for i in drive_ids)
                raise ImageMounted(
                    f"このイメージは現在 {drives} に挿入されています。先にイジェクトしてください。"
                )

            if target_resolved in mounted_path.parents:
                drives = " と ".join(f"Drive {i}" for i in drive_ids)
                raise ImageMounted(
                    f"このフォルダには {drives} に挿入中のイメージが含まれています。"
                    "先にイジェクトしてください。"
                )

    # --- 一覧 ---------------------------------------------------------------

    async def list_directory(self, relative: str | None) -> ImageListing:
        """1 階層分の一覧を返す。

        ツリー表示はノードを開くたびにこれを呼ぶ（遅延読み込み）。
        再帰的に読まないのは、イメージが増えたときに Pi では重くなるため。
        """
        target = self.resolve(relative)

        if not target.exists():
            raise NotFound(f"フォルダが見つかりません: {relative or '/'}")
        if not target.is_dir():
            raise InvalidPath("フォルダではありません。")

        mounted = await self.mounted_paths()
        entries = await asyncio.to_thread(self._scan_directory, target, mounted)
        entries.sort(key=entry_sort_key)

        return ImageListing(path=self.to_relative(target), entries=entries)

    def _scan_directory(self, directory: Path, mounted: dict[Path, list[int]]) -> list[ImageEntry]:
        entries: list[ImageEntry] = []

        for child in directory.iterdir():
            # 書き込み途中の一時ファイルは一覧に出さない
            if child.name.endswith(PART_SUFFIX):
                continue

            try:
                stat = child.stat()
            except OSError:
                # 走査中に外部で削除された場合は黙って飛ばす
                continue

            kind = classify(child)
            is_dir = kind is ImageKind.DIRECTORY

            try:
                resolved = child.resolve()
            except OSError:
                resolved = child

            entries.append(
                ImageEntry(
                    name=child.name,
                    path=self.to_relative(child),
                    kind=kind,
                    size=None if is_dir else stat.st_size,
                    # UTC の ISO8601 で返し、ローカル時刻への変換はブラウザに任せる。
                    # Pi 側のタイムゾーン設定に表示が左右されないようにするため。
                    mtime=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                    mounted_on=mounted.get(resolved, []),
                )
            )

        return entries

    # --- 作成 ---------------------------------------------------------------

    async def make_directory(self, parent: str | None, name: str) -> str:
        """新規フォルダを作成する。"""
        target = path_utils.safe_join(self.root, parent, name)

        if target.exists():
            raise AlreadyExists(f"「{name}」は既に存在します。")

        await asyncio.to_thread(target.mkdir, parents=False, exist_ok=False)
        logger.info("フォルダを作成しました: %s", target)
        return self.to_relative(target)

    async def create_image(
        self,
        parent: str | None,
        name: str,
        *,
        disk_type: DiskType = DiskType.TWO_HD,
        disk_name: str | None = None,
        write_protected: bool = False,
        data_format: DataFormat = DataFormat.ENCODE,
    ) -> str:
        """ブランクの FDX イメージを作成する。

        生成されるのは未フォーマットのディスクであり、
        使用前に X68000 側で FORMAT.X によるフォーマットが必要。
        """
        # 拡張子が付いていなければ補う
        if not name.lower().endswith(FDX_EXTENSION):
            name = f"{name}{FDX_EXTENSION}"

        target = path_utils.safe_join(self.root, parent, name)

        if target.exists():
            raise AlreadyExists(f"「{name}」は既に存在します。")

        try:
            await self._backend.create_blank_image(
                target,
                disk_type=disk_type,
                disk_name=disk_name,
                write_protected=write_protected,
                data_format=data_format,
            )
        except Exception:
            # 作成に失敗して中途半端なファイルが残っていたら消す
            await self._cleanup(target)
            raise

        if not target.exists():
            raise NotFound("イメージの作成に失敗しました。")

        logger.info("ブランクイメージを作成しました: %s (%s)", target, disk_type.value)
        return self.to_relative(target)

    # --- 変換 ---------------------------------------------------------------

    async def convert(
        self,
        relative: str,
        *,
        disk_no: int = 1,
        data_format: DataFormat = DataFormat.ENCODE,
        analyze: AnalyzeMode = AnalyzeMode.UPD765,
    ) -> str:
        """非 FDX のイメージを FDX に変換する。

        元ファイルは変更しない。変換先が既にあれば上書きせず拒否する。
        """
        source = self._require_existing(relative)

        if source.is_dir():
            raise InvalidPath("フォルダは変換できません。")

        if classify(source) is not ImageKind.CONVERTIBLE_IMAGE:
            raise UnsupportedFileType(f"「{source.name}」は FDX に変換できる形式ではありません。")

        destination = source.with_suffix(FDX_EXTENSION)

        if destination.exists():
            raise AlreadyExists(
                f"変換先「{destination.name}」が既に存在します。"
                "上書きはしません。先に削除するか名前を変更してください。"
            )

        try:
            await self._backend.convert_to_fdx(
                source,
                destination,
                disk_no=disk_no,
                data_format=data_format,
                analyze=analyze,
            )
        except Exception:
            await self._cleanup(destination)
            raise

        logger.info("変換しました: %s -> %s", source, destination)
        return self.to_relative(destination)

    # --- ディスク情報 -------------------------------------------------------

    async def get_info(self, relative: str) -> DiskInfo:
        target = self._require_existing(relative)
        self._require_fdx(target)
        return await self._backend.get_disk_info(target)

    def resolve_for_download(self, relative: str) -> Path:
        """ダウンロード対象のパスを解決する。

        フォルダの ZIP 化は Pi の CPU に対して重すぎるため対応しない。
        """
        target = self._require_existing(relative)
        if target.is_dir():
            raise NotFound("フォルダはダウンロードできません。")
        return target

    async def set_attributes(
        self,
        relative: str,
        *,
        disk_name: str | None = None,
        write_protected: bool | None = None,
    ) -> None:
        """FDX ファイル自体のディスク名・WP 属性を変更する。

        ファイルを書き換えるため、挿入中のイメージには適用しない。
        """
        target = self._require_existing(relative)
        self._require_fdx(target)

        await self.assert_not_mounted(target)
        await self._backend.set_disk_attributes(
            target, disk_name=disk_name, write_protected=write_protected
        )
        logger.info("ディスク属性を変更しました: %s", target)

    # --- リネーム・移動・複製 -----------------------------------------------

    async def rename(self, relative: str, new_name: str) -> str:
        """ファイルまたはフォルダの名前を変更する。"""
        target = self._require_existing(relative)
        self._reject_root(target, "名前を変更")

        await self.assert_not_mounted(target)

        validated = path_utils.validate_name(new_name)
        destination = target.parent / validated

        if not path_utils.is_within(self.root, destination):
            raise InvalidPath()

        if destination.exists():
            raise AlreadyExists(f"「{validated}」は既に存在します。")

        await asyncio.to_thread(target.rename, destination)
        logger.info("名前を変更しました: %s -> %s", target, destination)
        return self.to_relative(destination)

    async def move(self, relative: str, dest_dir: str | None, *, copy: bool = False) -> str:
        """ファイルまたはフォルダを別のディレクトリへ移動（またはコピー）する。"""
        source = self._require_existing(relative)
        destination_dir = self.resolve(dest_dir)

        self._reject_root(source, "移動")
        if not destination_dir.exists() or not destination_dir.is_dir():
            raise NotFound("移動先のフォルダが見つかりません。")

        # 同じディレクトリへの移動は何もせず成功として扱う
        if source.parent.resolve() == destination_dir.resolve():
            return self.to_relative(source)

        # フォルダを自分自身、または自分の子孫へ移動させない。
        # この検査を忘れるとディレクトリツリーが壊れて復旧できなくなる。
        if source.is_dir():
            source_resolved = source.resolve()
            dest_resolved = destination_dir.resolve()
            if dest_resolved == source_resolved or source_resolved in dest_resolved.parents:
                raise InvalidPath("フォルダを自分自身の中へ移動することはできません。")

        if not copy:
            await self.assert_not_mounted(source)

        destination = destination_dir / source.name
        if destination.exists():
            raise AlreadyExists(f"移動先に「{source.name}」が既に存在します。")

        if copy:
            await self._copy(source, destination)
        else:
            try:
                await asyncio.to_thread(os.rename, source, destination)
            except OSError as exc:
                if exc.errno == 18:  # EXDEV
                    # 黙ってコピー＆削除にフォールバックしない。
                    # 巨大なイメージで長時間ブロックしたうえ、失敗時に消失しかねないため。
                    raise InvalidPath(
                        "異なるドライブ間の移動には対応していません。"
                        "コピーしてから元を削除してください。",
                        detail=str(exc),
                    ) from exc
                raise

        logger.info("%s しました: %s -> %s", "コピー" if copy else "移動", source, destination)
        return self.to_relative(destination)

    async def duplicate(self, relative: str) -> str:
        """同一ディレクトリに複製を作る。

        「マスターを残したまま、コピーを実機に挿して書き込ませる」
        という X68000 で頻繁に必要になる使い方のための機能。
        """
        source = self._require_existing(relative)

        if source.is_dir():
            raise InvalidPath("フォルダの複製には対応していません。")

        destination = self._next_copy_name(source)
        await self._copy(source, destination)

        logger.info("複製しました: %s -> %s", source, destination)
        return self.to_relative(destination)

    @staticmethod
    def _next_copy_name(source: Path) -> Path:
        """`disk.fdx` -> `disk copy.fdx` -> `disk copy 2.fdx` の順で空き名を探す。"""
        stem = source.stem
        suffix = source.suffix

        candidate = source.parent / f"{stem} copy{suffix}"
        if not candidate.exists():
            return candidate

        index = 2
        while True:
            candidate = source.parent / f"{stem} copy {index}{suffix}"
            if not candidate.exists():
                return candidate
            index += 1

    async def _copy(self, source: Path, destination: Path) -> None:
        """`.part` 経由でコピーする。

        コピー途中の中途半端なファイルを、正式な名前で一覧に見せないため。
        """
        await self._check_space(destination.parent, source.stat().st_size)

        part = destination.with_name(destination.name + PART_SUFFIX)
        try:
            # 数十 MB になりうるためイベントループを塞がない
            await asyncio.to_thread(shutil.copy2, source, part)
            await asyncio.to_thread(os.replace, part, destination)
        except Exception:
            await self._cleanup(part)
            raise

    # --- アップロード -------------------------------------------------------

    async def save_upload(self, dest_dir: str | None, filename: str, reader: ChunkReader) -> str:
        """アップロードされたファイルを保存する。

        メモリに全体を載せないよう、必ずチャンク単位で読み書きする。
        Raspberry Pi の空きメモリは 275MB しかなく、
        上限の 256MB を一度に載せる実装では動かない。
        """
        directory = self.resolve(dest_dir)
        if not directory.exists() or not directory.is_dir():
            raise NotFound("保存先のフォルダが見つかりません。")

        # クライアント由来のファイル名は必ずベース名に切り詰める。
        # ブラウザのフォルダドロップでは相対パス付きの名前が来ることがあり、
        # そのまま結合するとルート外に書き出せてしまう。
        safe_name = path_utils.sanitize_upload_filename(filename)

        suffix = Path(safe_name).suffix.lower()
        if suffix not in UPLOADABLE_EXTENSIONS:
            raise UnsupportedFileType(
                f"「{safe_name}」は対応していない形式です。"
                "FDX または変換可能なディスクイメージのみアップロードできます。"
            )

        destination = directory / safe_name
        if not path_utils.is_within(self.root, destination):
            raise InvalidPath()

        if destination.exists():
            raise AlreadyExists(f"「{safe_name}」は既に存在します。上書きはしません。")

        part = destination.with_name(destination.name + PART_SUFFIX)
        limit = self._settings.max_upload_bytes
        written = 0

        try:
            with part.open("wb") as out:
                while True:
                    chunk = await reader.read(UPLOAD_CHUNK_SIZE)
                    if not chunk:
                        break

                    written += len(chunk)
                    if written > limit:
                        raise UploadTooLarge(
                            f"ファイルが大きすぎます（上限 {self._settings.max_upload_mb}MB）。"
                        )
                    await asyncio.to_thread(out.write, chunk)

            await asyncio.to_thread(os.replace, part, destination)
        except Exception:
            # 通信断・容量不足・上限超過のいずれでも .part を残さない
            await self._cleanup(part)
            raise

        logger.info("アップロードしました: %s (%d バイト)", destination, written)
        return self.to_relative(destination)

    # --- 削除 ---------------------------------------------------------------

    async def delete(self, relative: str) -> None:
        """ファイルまたは空のディレクトリを削除する。"""
        target = self._require_existing(relative)
        self._reject_root(target, "削除")

        await self.assert_not_mounted(target)

        if target.is_dir():
            # 再帰削除は行わない。安全側に倒している。
            if any(target.iterdir()):
                raise DirectoryNotEmpty(
                    f"「{target.name}」は空ではありません。中のファイルを先に削除してください。"
                )
            await asyncio.to_thread(target.rmdir)
        else:
            await asyncio.to_thread(target.unlink)

        logger.info("削除しました: %s", target)

    # --- 補助 ---------------------------------------------------------------

    async def _check_space(self, directory: Path, required: int) -> None:
        usage = await asyncio.to_thread(shutil.disk_usage, directory)
        # 余裕を見て 1.1 倍で判定する
        if usage.free < required * 1.1:
            raise InsufficientSpace()

    @staticmethod
    async def _cleanup(path: Path) -> None:
        """中途半端なファイルを削除する。失敗しても例外にしない。"""
        try:
            if path.exists():
                await asyncio.to_thread(path.unlink)
                logger.info("中途半端なファイルを削除しました: %s", path)
        except OSError:
            logger.warning("一時ファイルを削除できませんでした: %s", path, exc_info=True)
