"""アップロードの Integration Test。

クライアント由来のファイル名は信用できないため、そこを重点的に確認する。
"""

from pathlib import Path

from httpx import AsyncClient


def _file(name: str, content: bytes = b"FDX68-MOCK-IMAGE\n"):
    return {"files": (name, content, "application/octet-stream")}


async def test_アップロード(client: AsyncClient, image_root: Path):
    response = await client.post(
        "/api/images/upload", data={"path": ""}, files=_file("uploaded.fdx")
    )
    assert response.status_code == 200
    assert response.json()["results"][0]["success"] is True
    assert (image_root / "uploaded.fdx").exists()


async def test_フォルダを指定してアップロード(client: AsyncClient, image_root: Path):
    response = await client.post(
        "/api/images/upload", data={"path": "ゲーム"}, files=_file("uploaded.fdx")
    )
    assert response.json()["results"][0]["success"] is True
    assert (image_root / "ゲーム" / "uploaded.fdx").exists()


async def test_相対パス付きのファイル名はベース名に切り詰められる(
    client: AsyncClient, image_root: Path
):
    """ブラウザのフォルダドロップでこの形式の名前が実際に送られてくる。

    そのまま結合するとイメージルートの外に書き出せてしまう。
    """
    response = await client.post(
        "/api/images/upload", data={"path": ""}, files=_file("../../evil.fdx")
    )
    assert response.json()["results"][0]["success"] is True

    # ルート直下に切り詰められた名前で保存される
    assert (image_root / "evil.fdx").exists()
    # 親ディレクトリには漏れていない
    assert not (image_root.parent / "evil.fdx").exists()


async def test_サブディレクトリ付きのファイル名も切り詰められる(
    client: AsyncClient, image_root: Path
):
    response = await client.post(
        "/api/images/upload", data={"path": ""}, files=_file("sub/dir/nested.fdx")
    )
    assert response.json()["results"][0]["success"] is True
    assert (image_root / "nested.fdx").exists()


async def test_日本語のファイル名(client: AsyncClient, image_root: Path):
    response = await client.post(
        "/api/images/upload", data={"path": ""}, files=_file("闇の血族1.fdx")
    )
    assert response.json()["results"][0]["success"] is True
    assert (image_root / "闇の血族1.fdx").exists()


async def test_対応していない拡張子は拒否される(client: AsyncClient, image_root: Path):
    """イメージ置き場が任意のファイル置き場にならないようにする。"""
    response = await client.post(
        "/api/images/upload", data={"path": ""}, files=_file("script.sh", b"#!/bin/sh")
    )
    result = response.json()["results"][0]

    assert result["success"] is False
    assert not (image_root / "script.sh").exists()


async def test_変換可能な形式はアップロードできる(client: AsyncClient, image_root: Path):
    response = await client.post(
        "/api/images/upload", data={"path": ""}, files=_file("game.d88", b"D88")
    )
    assert response.json()["results"][0]["success"] is True
    assert (image_root / "game.d88").exists()


async def test_同名ファイルは上書きされない(client: AsyncClient, image_root: Path):
    before = (image_root / "disk1.fdx").read_bytes()

    response = await client.post(
        "/api/images/upload", data={"path": ""}, files=_file("disk1.fdx", "新しい内容".encode())
    )
    assert response.json()["results"][0]["success"] is False
    assert (image_root / "disk1.fdx").read_bytes() == before


async def test_サイズ上限を超えると中断され_partが残らない(client: AsyncClient, image_root: Path):
    """上限は conftest で 1MB に設定してある。"""
    oversized = b"x" * (2 * 1024 * 1024)

    response = await client.post(
        "/api/images/upload", data={"path": ""}, files=_file("big.fdx", oversized)
    )
    result = response.json()["results"][0]

    assert result["success"] is False
    assert not (image_root / "big.fdx").exists()
    # 中途半端なファイルを残さない
    assert not list(image_root.glob("*.part"))


async def test_複数ファイルのアップロード(client: AsyncClient, image_root: Path):
    response = await client.post(
        "/api/images/upload",
        data={"path": ""},
        files=[
            ("files", ("a.fdx", b"A", "application/octet-stream")),
            ("files", ("b.fdx", b"B", "application/octet-stream")),
        ],
    )
    results = response.json()["results"]

    assert len(results) == 2
    assert all(r["success"] for r in results)
    assert (image_root / "a.fdx").exists()
    assert (image_root / "b.fdx").exists()


async def test_一部が失敗しても残りは処理される(client: AsyncClient, image_root: Path):
    response = await client.post(
        "/api/images/upload",
        data={"path": ""},
        files=[
            ("files", ("ok.fdx", b"OK", "application/octet-stream")),
            ("files", ("bad.exe", b"NG", "application/octet-stream")),
        ],
    )
    results = response.json()["results"]

    assert results[0]["success"] is True
    assert results[1]["success"] is False
    assert (image_root / "ok.fdx").exists()


async def test_ルート外へのアップロードは拒否される(client: AsyncClient):
    response = await client.post(
        "/api/images/upload", data={"path": "../"}, files=_file("evil.fdx")
    )
    assert response.status_code == 400


# --- 自動変換 ---------------------------------------------------------------


def _auto(path: str = "") -> dict[str, str]:
    return {"path": path, "auto_convert": "true"}


async def test_自動変換で元ファイルとFDXの両方が残る(client: AsyncClient, image_root: Path):
    response = await client.post("/api/images/upload", data=_auto(), files=_file("game.d88"))
    result = response.json()["results"][0]

    assert result["success"] is True
    assert result["path"] == "game.d88"
    assert result["converted_path"] == "game.fdx"
    assert result["message"] is None
    assert (image_root / "game.d88").exists()
    assert (image_root / "game.fdx").exists()


async def test_自動変換はフォルダ内に変換先を作る(client: AsyncClient, image_root: Path):
    response = await client.post(
        "/api/images/upload", data=_auto("ゲーム"), files=_file("game.xdf")
    )
    assert response.json()["results"][0]["converted_path"] == "ゲーム/game.fdx"
    assert (image_root / "ゲーム" / "game.fdx").exists()


async def test_FDXは自動変換の対象にならない(client: AsyncClient, image_root: Path):
    response = await client.post("/api/images/upload", data=_auto(), files=_file("new.fdx"))
    result = response.json()["results"][0]

    assert result["success"] is True
    assert result["converted_path"] is None


async def test_自動変換の指定がなければ変換しない(client: AsyncClient, image_root: Path):
    """API の既定は従来通り。"""
    response = await client.post("/api/images/upload", data={"path": ""}, files=_file("game.d88"))
    assert response.json()["results"][0]["converted_path"] is None
    assert not (image_root / "game.fdx").exists()


async def test_変換先のFDXが既にあれば上書きせず元ファイルだけ保存する(
    client: AsyncClient, image_root: Path
):
    """既存の FDX は実機で書き込まれたセーブディスクかもしれない。"""
    before = (image_root / "disk1.fdx").read_bytes()

    response = await client.post("/api/images/upload", data=_auto(), files=_file("disk1.d88"))
    result = response.json()["results"][0]

    assert result["success"] is True
    assert result["converted_path"] is None
    assert "disk1.fdx" in result["message"]
    assert (image_root / "disk1.d88").exists()
    assert (image_root / "disk1.fdx").read_bytes() == before


async def test_拡張子の大文字小文字だけ違うFDXも既存として扱う(
    client: AsyncClient, image_root: Path
):
    """Pi の ext4 では GAME.FDX と GAME.fdx が共存できてしまうため。"""
    (image_root / "GAME.FDX").write_bytes(b"EXISTING")

    response = await client.post("/api/images/upload", data=_auto(), files=_file("GAME.D88"))
    result = response.json()["results"][0]

    assert result["success"] is True
    assert result["converted_path"] is None
    assert "GAME.FDX" in result["message"]
    assert (image_root / "GAME.FDX").read_bytes() == b"EXISTING"
    assert "GAME.fdx" not in [p.name for p in image_root.iterdir()]


async def test_同じリクエスト内で変換先が衝突したら先の方だけ変換する(
    client: AsyncClient, image_root: Path
):
    response = await client.post(
        "/api/images/upload",
        data=_auto(),
        files=[
            ("files", ("game.d88", b"D88", "application/octet-stream")),
            ("files", ("game.xdf", b"XDF", "application/octet-stream")),
        ],
    )
    first, second = response.json()["results"]

    assert first["converted_path"] == "game.fdx"
    assert second["success"] is True
    assert second["converted_path"] is None
    assert second["message"] is not None
    assert (image_root / "game.xdf").exists()
