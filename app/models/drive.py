"""ドライブとエミュレータの状態を表すモデル。"""

from pydantic import BaseModel, Field


class Drive(BaseModel):
    """1 台の FDD エミュレーションドライブの状態。

    `fddctl -l` の 1 行に対応する。
    """

    id: int = Field(description="ドライブ番号（0 または 1）")
    inserted: bool = Field(description="ディスクイメージが挿入されているか")
    write_protected: bool = Field(description="ライトプロテクトが有効か（fddemu の実行時状態）")
    cylinder: int | None = Field(
        default=None,
        description="現在のシリンダ位置。数値として解釈できなかった場合は None",
    )
    cylinder_raw: str | None = Field(
        default=None,
        description="fddctl -l が出力したシリンダ欄の生の文字列。"
        "書式が変わって解釈に失敗しても、情報を失わず表示できるようにするため保持する",
    )
    image: str | None = Field(
        default=None,
        description="挿入中のイメージの絶対パス。未挿入なら None",
    )
    image_relative: str | None = Field(
        default=None,
        description="イメージルートからの相対パス。ルート外のイメージが挿入されている場合は None",
    )


class FDX68Status(BaseModel):
    """FDX68 全体の状態。"""

    fddemu_running: bool = Field(description="fddemu が動作しているか")
    drives: list[Drive] = Field(default_factory=list)
    message: str | None = Field(
        default=None,
        description="fddemu 停止中など、状態に関する補足メッセージ",
    )
