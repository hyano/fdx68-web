"""アプリケーション共通の例外。

API 層でこれらを HTTP ステータスに対応付ける。
ユーザーに見せるメッセージは日本語で、技術的な詳細はログに残す。
"""


class FDX68Error(Exception):
    """このアプリケーションが送出する例外の基底クラス。"""

    #: API 層が返す HTTP ステータスコード
    status_code = 500

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        #: ログに残す技術的な詳細（ユーザーには見せない）
        self.detail = detail


class FddemuNotRunning(FDX68Error):
    """fddemu が起動していない。

    これは異常ではなく通常起こりうる状態なので、
    状態取得の文脈ではエラーにせず「停止中」として扱うこと。
    """

    status_code = 409

    def __init__(self, message: str = "fddemu が起動していません。", **kwargs: str) -> None:
        super().__init__(message, **kwargs)


class InvalidPath(FDX68Error):
    """イメージルートの外を指すパス、または不正な名前。"""

    status_code = 400

    def __init__(self, message: str = "許可されていないパスです。", **kwargs: str) -> None:
        super().__init__(message, **kwargs)


class InvalidParameter(FDX68Error):
    """パス以外のリクエスト値が不正。

    パスの不正は InvalidPath を使うこと。
    例外名と実態を一致させておかないと、ログから原因を追えなくなる。
    """

    status_code = 400

    def __init__(self, message: str, **kwargs: str) -> None:
        super().__init__(message, **kwargs)


class NotFound(FDX68Error):
    """対象のファイルまたはディレクトリが存在しない。

    外部（SSH や rsync）で削除された場合にも発生する。異常ではなく通常起こりうる。
    """

    status_code = 404

    def __init__(self, message: str = "ファイルが存在しません。", **kwargs: str) -> None:
        super().__init__(message, **kwargs)


class AlreadyExists(FDX68Error):
    """作成先・変換先・移動先が既に存在する。

    ディスクイメージを無断で上書きしないための拒否。
    """

    status_code = 409

    def __init__(
        self, message: str = "同じ名前のファイルが既に存在します。", **kwargs: str
    ) -> None:
        super().__init__(message, **kwargs)


class ImageMounted(FDX68Error):
    """挿入中のイメージに対する破壊的操作。

    fddemu は挿入時のパスを保持しているため、削除・リネーム・移動すると参照が壊れる。
    """

    status_code = 409

    def __init__(self, message: str, **kwargs: str) -> None:
        super().__init__(message, **kwargs)


class DirectoryNotEmpty(FDX68Error):
    """空でないディレクトリの削除。"""

    status_code = 409

    def __init__(self, message: str = "ディレクトリが空ではありません。", **kwargs: str) -> None:
        super().__init__(message, **kwargs)


class CommandFailed(FDX68Error):
    """FDX68 コマンドの実行に失敗した。"""

    status_code = 500

    def __init__(self, message: str, **kwargs: str) -> None:
        super().__init__(message, **kwargs)


class UploadTooLarge(FDX68Error):
    """アップロードのサイズが上限を超えた。"""

    status_code = 413

    def __init__(self, message: str, **kwargs: str) -> None:
        super().__init__(message, **kwargs)


class UnsupportedFileType(FDX68Error):
    """対応していない拡張子。"""

    status_code = 400

    def __init__(self, message: str, **kwargs: str) -> None:
        super().__init__(message, **kwargs)


class InsufficientSpace(FDX68Error):
    """ディスクの空き容量が不足している。"""

    status_code = 507

    def __init__(
        self, message: str = "ディスクの空き容量が不足しています。", **kwargs: str
    ) -> None:
        super().__init__(message, **kwargs)
