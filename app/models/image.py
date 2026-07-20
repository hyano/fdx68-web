"""ディスクイメージとファイル一覧を表すモデル。"""

from enum import StrEnum

from pydantic import BaseModel, Field

# FDX 形式の拡張子
FDX_EXTENSION = ".fdx"

# fdxconv で FDX に変換できる拡張子。
# 出典: http://retropc.net/gimons/fdx68/command.html
CONVERTIBLE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".xdf",
        ".2hd",
        ".hdm",
        ".img",
        ".dup",
        ".2hc",
        ".2hq",
        ".2dd",
        ".dim",
        ".d88",
        ".d68",
        ".d77",
        ".fdi",
        ".fdd",
        ".nfd",
    }
)

# アップロードを許可する拡張子（FDX と変換可能形式のみ）。
# これを制限しないと、イメージ置き場が任意のファイル置き場になってしまう。
UPLOADABLE_EXTENSIONS: frozenset[str] = CONVERTIBLE_EXTENSIONS | {FDX_EXTENSION}


class ImageKind(StrEnum):
    """ファイルの種別。

    Web UI ではこの値を data-kind 属性としてそのまま出力し、
    アイコンやバッジの表示を CSS 側で決める。
    """

    DIRECTORY = "directory"
    FDX = "fdx"
    CONVERTIBLE_IMAGE = "convertible_image"
    UNSUPPORTED = "unsupported"


class DiskType(StrEnum):
    """新規作成するディスクの種別。

    X68000 で使うのは 2HD（5.25 インチ、360rpm）。
    """

    TWO_D = "2D"
    TWO_DD = "2DD"
    TWO_HD = "2HD"


class DataFormat(StrEnum):
    """FDX のデータ形式。"""

    ENCODE = "encode"
    RAW = "raw"


class AnalyzeMode(StrEnum):
    """エンコードデータの解析モード。

    X68000 や NEC 系は upd765、FM 系・X1 系は mb8877。
    """

    UPD765 = "upd765"
    MB8877 = "mb8877"


class ImageEntry(BaseModel):
    """ファイル一覧の 1 項目。"""

    name: str = Field(description="ファイル名（パスを含まない）")
    path: str = Field(description="イメージルートからの相対パス")
    kind: ImageKind
    size: int | None = Field(default=None, description="バイト数。ディレクトリなら None")
    mtime: str | None = Field(
        default=None,
        description="更新日時（ISO8601 の UTC）。表示のタイムゾーン変換はブラウザ側で行う",
    )
    mounted_on: list[int] = Field(
        default_factory=list,
        description="このイメージが挿入されているドライブ番号。挿入されていなければ空",
    )


class ImageListing(BaseModel):
    """1 ディレクトリ分の一覧。

    ツリー表示はノードを開くたびにこれを 1 階層分だけ取得する。
    """

    path: str = Field(description="このディレクトリのイメージルートからの相対パス")
    entries: list[ImageEntry] = Field(default_factory=list)


class DiskInfo(BaseModel):
    """fdxtool で取得した FDX のディスク情報。"""

    name: str | None = None
    disk_type: str | None = None
    rpm: int | None = None
    cylinders: int | None = None
    heads: int | None = None
    data_format: str | None = None
    write_protected: bool | None = None
    raw_output: str = Field(
        description="fdxtool の生の出力。"
        "パースに失敗しても情報を失わないよう、常に保持して UI でそのまま表示できるようにする"
    )


class OperationResult(BaseModel):
    """一括操作の結果。

    途中で失敗しても処理を止めず、最後にまとめて報告するために使う。
    """

    path: str
    success: bool
    message: str | None = None


class BulkResult(BaseModel):
    """一括操作全体の結果。"""

    results: list[OperationResult] = Field(default_factory=list)

    @property
    def succeeded(self) -> int:
        return sum(1 for r in self.results if r.success)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.success)
