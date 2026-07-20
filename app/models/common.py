"""複数の API で共通に使うレスポンスモデル。"""

from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    """利用者に見せるメッセージだけを返すレスポンス。

    エラー時のレスポンス（`{"message": ...}`）と形を揃えてある。
    フロントエンドが成否にかかわらず同じ取り出し方をできるようにするため。
    """

    message: str = Field(description="利用者に表示する日本語のメッセージ")
