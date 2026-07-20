"""ディスクイメージの管理。

一覧・変換・作成・移動・複製・アップロード・ダウンロード・削除。
"""

import logging
import urllib.parse
from pathlib import Path as FilePath

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from app.deps import ImageServiceDep, StatusMonitorDep
from app.errors import FDX68Error, NotFound
from app.models.image import (
    AnalyzeMode,
    BulkResult,
    DataFormat,
    DiskInfo,
    DiskType,
    ImageListing,
    OperationResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/images", tags=["images"])

PathQuery = Query(default="", description="イメージルートからの相対パス")


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
    target = images.resolve(path)

    if not target.exists():
        raise NotFound()
    if target.is_dir():
        # ZIP 化は Pi の CPU に対して重すぎるため対応しない
        raise NotFound("フォルダはダウンロードできません。")

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


@router.post("/mkdir")
async def mkdir(
    request: MkdirRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> dict[str, str]:
    """新規フォルダを作成する。"""
    created = await images.make_directory(request.parent, request.name)
    await monitor.notify_images_changed(request.parent)
    return {"path": created}


@router.post("/create")
async def create_image(
    request: CreateImageRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> dict[str, str]:
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
    return {"path": created}


@router.post("/convert")
async def convert(
    request: ConvertRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> dict[str, str]:
    """非 FDX のイメージを FDX に変換する。

    元ファイルは変更せず、変換先が既にあれば上書きせず拒否する。
    """
    created = await images.convert(
        request.path,
        disk_no=request.disk_no,
        data_format=request.data_format,
        analyze=request.analyze,
    )
    await monitor.notify_images_changed(str(FilePath(request.path).parent))
    return {"path": created}


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

    results: list[OperationResult] = []

    for upload_file in files:
        filename = upload_file.filename or ""
        try:
            saved = await images.save_upload(path, filename, reader=upload_file)
            results.append(OperationResult(path=saved, success=True))
        except FDX68Error as exc:
            logger.warning("アップロードに失敗しました: %s (%s)", filename, exc.detail)
            results.append(OperationResult(path=filename, success=False, message=exc.message))
        finally:
            await upload_file.close()

    if any(r.success for r in results):
        await monitor.notify_images_changed(path)

    return BulkResult(results=results)


# --- 移動・複製・リネーム ---------------------------------------------------


@router.post("/move", response_model=BulkResult)
async def move(
    request: MoveRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> BulkResult:
    """ファイル・フォルダを別のディレクトリへ移動（またはコピー）する。

    1 件ずつ順に処理し、途中で失敗しても中断しない。
    10 件選んで 1 件が挿入中だったときに 9 件が処理されないのは不便なため。
    """
    results: list[OperationResult] = []

    for source in request.paths:
        try:
            moved = await images.move(source, request.dest_dir, copy=request.as_copy)
            results.append(OperationResult(path=moved, success=True))
        except FDX68Error as exc:
            logger.warning("移動に失敗しました: %s (%s)", source, exc.detail)
            results.append(OperationResult(path=source, success=False, message=exc.message))

    if any(r.success for r in results):
        await monitor.notify_images_changed(request.dest_dir)

    return BulkResult(results=results)


@router.post("/duplicate")
async def duplicate(
    request: DuplicateRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> dict[str, str]:
    """同一ディレクトリに複製を作る。"""
    created = await images.duplicate(request.path)
    await monitor.notify_images_changed(str(FilePath(request.path).parent))
    return {"path": created}


@router.post("/rename")
async def rename(
    request: RenameRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> dict[str, str]:
    """名前を変更する。

    拡張子を変えても形式は変換されない旨は UI が注記する。
    """
    renamed = await images.rename(request.path, request.new_name)
    await monitor.notify_images_changed(str(FilePath(request.path).parent))
    return {"path": renamed}


@router.patch("/attributes")
async def set_attributes(
    request: AttributesRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> dict[str, str]:
    """FDX ファイル自体のディスク名・ライトプロテクト属性を変更する。

    ドライブの実行時プロテクト（/api/drives/{id}/protect）とは別物。
    """
    await images.set_attributes(
        request.path,
        disk_name=request.disk_name,
        write_protected=request.write_protected,
    )
    await monitor.notify_images_changed(str(FilePath(request.path).parent))
    return {"path": request.path}


# --- 削除 -------------------------------------------------------------------


@router.delete("", response_model=BulkResult)
async def delete(
    request: DeleteRequest, images: ImageServiceDep, monitor: StatusMonitorDep
) -> BulkResult:
    """ファイル・空のディレクトリを削除する。

    1 件ずつ順に処理し、挿入中のイメージが混ざっていてもその項目だけスキップする。
    """
    results: list[OperationResult] = []
    parents: set[str] = set()

    for target in request.paths:
        try:
            await images.delete(target)
            results.append(OperationResult(path=target, success=True))
            parents.add(str(FilePath(target).parent))
        except FDX68Error as exc:
            logger.warning("削除に失敗しました: %s (%s)", target, exc.detail)
            results.append(OperationResult(path=target, success=False, message=exc.message))

    for parent in parents:
        await monitor.notify_images_changed(parent)

    return BulkResult(results=results)
