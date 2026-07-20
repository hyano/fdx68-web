"""ファイル操作とガード条件の Integration Test。

ここのテストはディスクイメージを壊す事故を防ぐためのものなので、
拒否されるべきものが確実に拒否されることを重点的に確認する。
"""

from pathlib import Path

from httpx import AsyncClient


async def _insert(client: AsyncClient, drive_id: int, path: str) -> None:
    await client.post("/api/fddemu/start", json={})
    response = await client.post(f"/api/drives/{drive_id}/insert", json={"path": path})
    assert response.status_code == 200


# --- 作成 -------------------------------------------------------------------


async def test_新規フォルダの作成(client: AsyncClient, image_root: Path):
    response = await client.post("/api/images/mkdir", json={"parent": "", "name": "新しいフォルダ"})
    assert response.status_code == 200
    assert (image_root / "新しいフォルダ").is_dir()


async def test_既存と同名のフォルダは409(client: AsyncClient):
    response = await client.post("/api/images/mkdir", json={"parent": "", "name": "empty"})
    assert response.status_code == 409


async def test_不正な名前のフォルダは拒否される(client: AsyncClient):
    for name in ["../escape", "a/b", "..", ""]:
        response = await client.post("/api/images/mkdir", json={"parent": "", "name": name})
        assert response.status_code == 400, name


async def test_新規ディスクイメージの作成(client: AsyncClient, image_root: Path):
    response = await client.post(
        "/api/images/create",
        json={"parent": "", "name": "newdisk", "disk_type": "2HD", "disk_name": "TEST"},
    )
    assert response.status_code == 200

    # 拡張子が自動で補われる
    assert response.json()["path"] == "newdisk.fdx"
    assert (image_root / "newdisk.fdx").exists()


async def test_作成先が既にある場合は上書きしない(client: AsyncClient, image_root: Path):
    before = (image_root / "disk1.fdx").read_bytes()

    response = await client.post("/api/images/create", json={"parent": "", "name": "disk1.fdx"})
    assert response.status_code == 409
    assert (image_root / "disk1.fdx").read_bytes() == before


# --- 変換 -------------------------------------------------------------------


async def test_変換(client: AsyncClient, image_root: Path):
    response = await client.post("/api/images/convert", json={"path": "source.d88"})
    assert response.status_code == 200
    assert response.json()["path"] == "source.fdx"
    assert (image_root / "source.fdx").exists()


async def test_変換で元ファイルは変更されない(client: AsyncClient, image_root: Path):
    before = (image_root / "source.d88").read_bytes()
    await client.post("/api/images/convert", json={"path": "source.d88"})
    assert (image_root / "source.d88").read_bytes() == before


async def test_変換先が既にある場合は409(client: AsyncClient, image_root: Path):
    (image_root / "source.fdx").write_bytes("既存のデータ".encode())

    response = await client.post("/api/images/convert", json={"path": "source.d88"})
    assert response.status_code == 409
    # 上書きされていないこと
    assert (image_root / "source.fdx").read_bytes() == "既存のデータ".encode()


async def test_変換できない形式は拒否される(client: AsyncClient):
    response = await client.post("/api/images/convert", json={"path": "readme.txt"})
    assert response.status_code == 400


# --- 挿入中イメージのガード -------------------------------------------------


async def test_挿入中のイメージは削除できない(client: AsyncClient, image_root: Path):
    await _insert(client, 0, "disk1.fdx")

    response = await client.request("DELETE", "/api/images", json={"paths": ["disk1.fdx"]})
    assert response.status_code == 200

    result = response.json()["results"][0]
    assert result["success"] is False
    assert "Drive 0" in result["message"]
    assert (image_root / "disk1.fdx").exists()


async def test_挿入中のイメージはリネームできない(client: AsyncClient, image_root: Path):
    await _insert(client, 0, "disk1.fdx")

    response = await client.post(
        "/api/images/rename", json={"path": "disk1.fdx", "new_name": "renamed.fdx"}
    )
    assert response.status_code == 409
    assert (image_root / "disk1.fdx").exists()


async def test_挿入中のイメージは移動できない(client: AsyncClient, image_root: Path):
    await _insert(client, 0, "disk1.fdx")

    response = await client.post(
        "/api/images/move", json={"paths": ["disk1.fdx"], "dest_dir": "empty"}
    )
    assert response.json()["results"][0]["success"] is False
    assert (image_root / "disk1.fdx").exists()


async def test_挿入中のイメージは属性を変更できない(client: AsyncClient):
    """FDX ファイルを書き換えるため、エミュレーション中は拒否する。"""
    await _insert(client, 0, "disk1.fdx")

    response = await client.patch(
        "/api/images/attributes", json={"path": "disk1.fdx", "disk_name": "NEW"}
    )
    assert response.status_code == 409


async def test_挿入中イメージを含むフォルダは移動できない(client: AsyncClient, image_root: Path):
    """親フォルダを動かすと配下のパスがまとめて変わるため。"""
    await _insert(client, 0, "ゲーム/disk1.fdx")

    response = await client.post(
        "/api/images/move", json={"paths": ["ゲーム"], "dest_dir": "empty"}
    )
    assert response.json()["results"][0]["success"] is False
    assert (image_root / "ゲーム").is_dir()


async def test_挿入中でも複製はできる(client: AsyncClient, image_root: Path):
    """読み取りのみなので許可する（UI で注意は表示する）。"""
    await _insert(client, 0, "disk1.fdx")

    response = await client.post("/api/images/duplicate", json={"path": "disk1.fdx"})
    assert response.status_code == 200
    assert (image_root / "disk1 copy.fdx").exists()


# --- 移動 -------------------------------------------------------------------


async def test_移動(client: AsyncClient, image_root: Path):
    response = await client.post(
        "/api/images/move", json={"paths": ["disk1.fdx"], "dest_dir": "empty"}
    )
    assert response.json()["results"][0]["success"] is True
    assert (image_root / "empty" / "disk1.fdx").exists()
    assert not (image_root / "disk1.fdx").exists()


async def test_コピー(client: AsyncClient, image_root: Path):
    response = await client.post(
        "/api/images/move",
        json={"paths": ["disk1.fdx"], "dest_dir": "empty", "copy": True},
    )
    assert response.json()["results"][0]["success"] is True
    assert (image_root / "empty" / "disk1.fdx").exists()
    # コピーなので元も残る
    assert (image_root / "disk1.fdx").exists()


async def test_フォルダを自分自身の中へ移動できない(client: AsyncClient, image_root: Path):
    """これを許すとディレクトリツリーが壊れて復旧できなくなる。"""
    response = await client.post(
        "/api/images/move", json={"paths": ["ゲーム"], "dest_dir": "ゲーム"}
    )
    assert response.json()["results"][0]["success"] is False
    assert (image_root / "ゲーム").is_dir()


async def test_フォルダを自分の子孫へ移動できない(client: AsyncClient, image_root: Path):
    response = await client.post(
        "/api/images/move", json={"paths": ["ゲーム"], "dest_dir": "ゲーム/sub"}
    )
    assert response.json()["results"][0]["success"] is False
    assert (image_root / "ゲーム").is_dir()
    assert (image_root / "ゲーム" / "sub").is_dir()


async def test_同一ディレクトリへの移動は何もせず成功する(client: AsyncClient, image_root: Path):
    response = await client.post("/api/images/move", json={"paths": ["disk1.fdx"], "dest_dir": ""})
    assert response.json()["results"][0]["success"] is True
    assert (image_root / "disk1.fdx").exists()


async def test_移動先に同名があれば拒否される(client: AsyncClient, image_root: Path):
    (image_root / "empty" / "disk1.fdx").write_bytes("既存".encode())

    response = await client.post(
        "/api/images/move", json={"paths": ["disk1.fdx"], "dest_dir": "empty"}
    )
    assert response.json()["results"][0]["success"] is False
    assert (image_root / "empty" / "disk1.fdx").read_bytes() == "既存".encode()


# --- 複製 -------------------------------------------------------------------


async def test_複製は連番で作られる(client: AsyncClient, image_root: Path):
    first = await client.post("/api/images/duplicate", json={"path": "disk1.fdx"})
    assert first.json()["path"] == "disk1 copy.fdx"

    second = await client.post("/api/images/duplicate", json={"path": "disk1.fdx"})
    assert second.json()["path"] == "disk1 copy 2.fdx"

    # 中途半端なファイルが残らないこと
    assert not list(image_root.glob("*.part"))


async def test_複製の内容は元と同じ(client: AsyncClient, image_root: Path):
    await client.post("/api/images/duplicate", json={"path": "disk1.fdx"})
    assert (image_root / "disk1 copy.fdx").read_bytes() == (image_root / "disk1.fdx").read_bytes()


# --- リネーム ---------------------------------------------------------------


async def test_リネーム(client: AsyncClient, image_root: Path):
    response = await client.post(
        "/api/images/rename", json={"path": "disk1.fdx", "new_name": "改名.fdx"}
    )
    assert response.status_code == 200
    assert (image_root / "改名.fdx").exists()


async def test_リネーム先が既にあれば409(client: AsyncClient):
    response = await client.post(
        "/api/images/rename", json={"path": "disk1.fdx", "new_name": "source.d88"}
    )
    assert response.status_code == 409


# --- 削除 -------------------------------------------------------------------


async def test_削除(client: AsyncClient, image_root: Path):
    response = await client.request("DELETE", "/api/images", json={"paths": ["disk1.fdx"]})
    assert response.json()["results"][0]["success"] is True
    assert not (image_root / "disk1.fdx").exists()


async def test_空でないフォルダは削除できない(client: AsyncClient, image_root: Path):
    response = await client.request("DELETE", "/api/images", json={"paths": ["ゲーム"]})
    assert response.json()["results"][0]["success"] is False
    assert (image_root / "ゲーム").is_dir()


async def test_空のフォルダは削除できる(client: AsyncClient, image_root: Path):
    response = await client.request("DELETE", "/api/images", json={"paths": ["empty"]})
    assert response.json()["results"][0]["success"] is True
    assert not (image_root / "empty").exists()


async def test_一括削除は失敗しても中断しない(client: AsyncClient, image_root: Path):
    """10 件選んで 1 件が挿入中でも、残り 9 件は削除されるべき。"""
    for index in range(9):
        (image_root / f"bulk{index}.fdx").write_bytes(b"x")

    await _insert(client, 0, "disk1.fdx")

    paths = [f"bulk{i}.fdx" for i in range(9)] + ["disk1.fdx"]
    response = await client.request("DELETE", "/api/images", json={"paths": paths})

    results = response.json()["results"]
    succeeded = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]

    assert len(succeeded) == 9
    assert len(failed) == 1
    assert failed[0]["path"] == "disk1.fdx"
    assert "Drive 0" in failed[0]["message"]

    # 挿入中のものだけが残っている
    assert (image_root / "disk1.fdx").exists()
    assert not (image_root / "bulk0.fdx").exists()


# --- ディスク情報 -----------------------------------------------------------


async def test_ディスク情報の取得(client: AsyncClient):
    response = await client.get("/api/images/info", params={"path": "disk1.fdx"})
    assert response.status_code == 200
    assert response.json()["name"] == "DISK1"
    # 解析できてもできなくても生の出力は保持する
    assert response.json()["raw_output"]


async def test_ディスク属性の変更(client: AsyncClient):
    response = await client.patch(
        "/api/images/attributes", json={"path": "disk1.fdx", "disk_name": "変更後"}
    )
    assert response.status_code == 200

    info = await client.get("/api/images/info", params={"path": "disk1.fdx"})
    assert info.json()["name"] == "変更後"


# --- ダウンロード -----------------------------------------------------------


async def test_ダウンロード(client: AsyncClient, image_root: Path):
    response = await client.get("/api/images/download", params={"path": "disk1.fdx"})
    assert response.status_code == 200
    assert response.content == (image_root / "disk1.fdx").read_bytes()


async def test_日本語ファイル名はRFC5987で符号化される(client: AsyncClient, image_root: Path):
    """filename= だけでは文字化けするため filename*=UTF-8'' を使う。"""
    (image_root / "日本語ディスク.fdx").write_bytes(b"x")

    response = await client.get("/api/images/download", params={"path": "日本語ディスク.fdx"})
    disposition = response.headers["content-disposition"]

    assert "filename*=UTF-8''" in disposition
    # パーセントエンコードされた名前が含まれること
    assert "%E6%97%A5%E6%9C%AC%E8%AA%9E" in disposition


async def test_フォルダはダウンロードできない(client: AsyncClient):
    response = await client.get("/api/images/download", params={"path": "ゲーム"})
    assert response.status_code == 404
