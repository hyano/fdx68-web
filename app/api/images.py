"""ディスクイメージの管理。

一覧・変換・作成・移動・複製・アップロード・ダウンロード・削除。
"""

import logging
import urllib.parse
from collections.abc import Awaitable, Callable, Iterable
from typing import TypeVar

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from app.deps import ImageServiceDep, StatusMonitorDep
from app.errors import FDX68Error
from app.models.image import (
    AnalyzeMode,
    BulkResult,
    DataFormat,
    DiskInfo,
    DiskType,
    ImageListing,
    OperationResult,
    PathResponse,
)
from app.services.paths import parent_of

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/images", tags=["images"])

PathQuery = Query(default="", description="イメージルートからの相対パス")

_Item = TypeVar("_Item")


async def _run_bulk(
    items: Iterable[_Item],
    operation: Callable[[_Item], Awaitable[str]],
    *,
    action: str,
    name_of: Callable[[_Item], str],
) -> BulkResult:
    """一括操作を 1 件ずつ実行し、失敗しても中断せずに結果をまとめる。

    10 件選んで 1 件が挿入中だったときに残り 9 件が処理されないのは不便なため、
    途中で止めずに最後まで進める。この方針を 1 箇所に集約しておくことで、
    新しい一括操作を追加したときに扱いがばらつかないようにする。

    `operation` は成功時に「結果の相対パス」を返し、
    失敗時は `FDX68Error` を送出する。
    """
    results: list[OperationResult] = []

    for item in items:
        try:
            results.append(OperationResult(path=await operation(item), success=True))
        except FDX68Error as exc:
            logger.warning("%sに失敗しました: %s (%s)", action, name_of(item), exc.detail)
            results.append(OperationResult(path=name_of(item), success=False, message=exc.message))

    return BulkResult(results=results)


# --- リクエストモデル -------------------------------------------------------


class MkdirRequest(BaseModel):
    parent: str = Field(default="", description="作成先の親ディレクトリ（相対パス）")
    name: str = Field(description="フォルダ名")


class CreateImageRequest(BaseModel):
    parent: str = Field(default="")
    name: str = Field(description="ファイル名（.fdx は自動で補われる）")
    disk_type: DiskType = Field(default=DiskType.TWO_HD, description="ディスク種別。X68000 は 2HD")
    disk_name: str | None = Field(
        default=None, description="ディスク名。未指定なら FDX68 既定の BLANK IMAGE"
    )
    write_protected: bool = False
    data_format: DataFormat = DataFormat.ENCODE


class ConvertRequest(BaseModel):
    path: str
    disk_no: int = Field(
        default=1, ge=1, description="D88/D68/D77 のマルチイメージでのディスク番号"
    )
    data_format: DataFormat = DataFormat.ENCODE
    analyze: AnalyzeMode = Field(default=AnalyzeMode.UPD765, description="X68000 は upd765")


class RenameRequest(BaseModel):
    path: str
    new_name: str


class MoveRequest(BaseModel):
    # JSON 上のフィールド名は "copy" だが、BaseModel.copy と衝突するため
    # Python 側の属性名は as_copy にしている。
    model_config = ConfigDict(populate_by_name=True)

    paths: list[str] = Field(description="移動するファイル・フォルダの相対パス")
    dest_dir: str = Field(default="", description="移動先ディレクトリの相対パス")
    as_copy: bool = Field(
        default=False, alias="copy", description="true ならコピー、false なら移動"
    )


class DuplicateRequest(BaseModel):
    path: str


class AttributesRequest(BaseModel):
    path: str
    disk_name: str | None = None
    write_protected: bool | None = None


class DeleteRequest(BaseModel):
    paths: list[str] = Field(description="削除するファイル・フォルダの相対パス")


# --- 一覧・情報 -------------------------------------------------------------


@router.get("", response_model=ImageListing)
async def list_images(images: ImageServiceDep, path: str = PathQuery) -> ImageListing:
    """1 階層分の一覧を返す。

    ツリー表示はノードを開くたびにこれを呼ぶ（遅延読み込み）。
    """
    return await images.list_directory(path)


@router.get("/info", response_model=DiskInfo)
async def get_info(images: ImageServiceDep, path: str = PathQuery) -> DiskInfo:
    """FDX のディスク情報を返す。"""
    return await images.get_info(path)


@router.get("/download")
async def download(images: ImageServiceDep, path: str = PathQuery) -> FileResponse:
    """ディスクイメージをダウンロードする。

    実機で書き込まれたセーブディスクの退避や、変換結果の回収に使う。
    """
    target = images.resolve_for_download(path)

    # 日本語ファイル名は RFC 5987 の filename* で指定する。
    # filename= だけでは文字化けする。
    quoted = urllib.parse.quote(target.name, safe="")
    disposition = f"attachment; filename*=UTF-8''{quoted}"

    return FileResponse(
        target,
        media_type="application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


# --- 作成 -------------------------------------------------------------------


@router.post("/mkdir", response_model=PathResponse)
async def mkdir(
    request: MkdirRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> PathResponse:
    """新規フォルダを作成する。"""
    created = await images.make_directory(request.parent, request.name)
    await monitor.notify_images_changed(request.parent)
    return PathResponse(path=created)


@router.post("/create", response_model=PathResponse)
async def create_image(
    request: CreateImageRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> PathResponse:
    """ブランクの FDX イメージを作成する。

    生成されるのは未フォーマットのディスク。
    使用前に X68000 側で FORMAT.X によるフォーマットが必要な旨は UI が案内する。
    """
    created = await images.create_image(
        request.parent,
        request.name,
        disk_type=request.disk_type,
        disk_name=request.disk_name,
        write_protected=request.write_protected,
        data_format=request.data_format,
    )
    await monitor.notify_images_changed(request.parent)
    return PathResponse(path=created)


@router.post("/convert", response_model=PathResponse)
async def convert(
    request: ConvertRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> PathResponse:
    """非 FDX のイメージを FDX に変換する。

    元ファイルは変更せず、変換先が既にあれば上書きせず拒否する。
    """
    created = await images.convert(
        request.path,
        disk_no=request.disk_no,
        data_format=request.data_format,
        analyze=request.analyze,
    )
    await monitor.notify_images_changed(parent_of(request.path))
    return PathResponse(path=created)


# --- アップロード -----------------------------------------------------------


@router.post("/upload", response_model=BulkResult)
async def upload(
    images: ImageServiceDep,
    monitor: StatusMonitorDep,
    path: str = Form(default=""),
    files: list[UploadFile] = File(...),
) -> BulkResult:
    """ディスクイメージをアップロードする。

    1 ファイルずつ順に処理し、途中で失敗しても残りを続ける。
    """
    # 保存先の検証はリクエスト全体に関わるため、ループの前に一度だけ行う。
    # ここで失敗したらどのファイルも保存できないので、個別の失敗として
    # 報告するのではなくリクエスト自体を拒否する。
    images.resolve(path)

    async def _save(upload_file: UploadFile) -> str:
        try:
            return await images.save_upload(path, upload_file.filename or "", upload_file)
        finally:
            # 成否にかかわらず必ず閉じる（一時ファイルを残さないため）
            await upload_file.close()

    result = await _run_bulk(
        files,
        _save,
        action="アップロード",
        name_of=lambda f: f.filename or "",
    )

    if any(r.success for r in result.results):
        await monitor.notify_images_changed(path)

    return result


# --- 移動・複製・リネーム ---------------------------------------------------


@router.post("/move", response_model=BulkResult)
async def move(
    request: MoveRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> BulkResult:
    """ファイル・フォルダを別のディレクトリへ移動（またはコピー）する。

    1 件ずつ順に処理し、途中で失敗しても中断しない。
    10 件選んで 1 件が挿入中だったときに 9 件が処理されないのは不便なため。
    """

    async def _move(source: str) -> str:
        return await images.move(source, request.dest_dir, copy=request.as_copy)

    result = await _run_bulk(
        request.paths,
        _move,
        action="コピー" if request.as_copy else "移動",
        name_of=lambda source: source,
    )

    if any(r.success for r in result.results):
        await monitor.notify_images_changed(request.dest_dir)

    return result


@router.post("/duplicate", response_model=PathResponse)
async def duplicate(
    request: DuplicateRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> PathResponse:
    """同一ディレクトリに複製を作る。"""
    created = await images.duplicate(request.path)
    await monitor.notify_images_changed(parent_of(request.path))
    return PathResponse(path=created)


@router.post("/rename", response_model=PathResponse)
async def rename(
    request: RenameRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> PathResponse:
    """名前を変更する。

    拡張子を変えても形式は変換されない旨は UI が注記する。
    """
    renamed = await images.rename(request.path, request.new_name)
    await monitor.notify_images_changed(parent_of(request.path))
    return PathResponse(path=renamed)


@router.patch("/attributes", response_model=PathResponse)
async def set_attributes(
    request: AttributesRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> PathResponse:
    """FDX ファイル自体のディスク名・ライトプロテクト属性を変更する。

    ドライブの実行時プロテクト（/api/drives/{id}/protect）とは別物。
    """
    await images.set_attributes(
        request.path,
        disk_name=request.disk_name,
        write_protected=request.write_protected,
    )
    await monitor.notify_images_changed(parent_of(request.path))
    return PathResponse(path=request.path)


# --- 削除 -------------------------------------------------------------------


@router.delete("", response_model=BulkResult)
async def delete(
    request: DeleteRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> BulkResult:
    """ファイル・空のディレクトリを削除する。

    1 件ずつ順に処理し、挿入中のイメージが混ざっていてもその項目だけスキップする。
    """

    async def _delete(target: str) -> str:
        await images.delete(target)
        return target

    result = await _run_bulk(
        request.paths,
        _delete,
        action="削除",
        name_of=lambda target: target,
    )

    for parent in {parent_of(r.path) for r in result.results if r.success}:
        await monitor.notify_images_changed(parent)

    return result
