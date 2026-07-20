"""状態取得・ドライブ操作・一覧表示の Integration Test。"""

from httpx import AsyncClient


async def test_health(client: AsyncClient):
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["backend"] == "mock"
    # フロントエンドはこの値の変化でサービスの再起動完了を判定する
    assert isinstance(response.json()["started_at"], float)


async def test_web_ui_サービスの再起動(client: AsyncClient):
    """mock では実際には再起動せず、要求されたことだけを記録する。"""
    response = await client.post("/api/system/restart-service")

    assert response.status_code == 200
    assert response.json()["message"]
    assert client.app.state.backend.service_restart_requested is True  # type: ignore[attr-defined]


async def test_fddemu_停止中でもエラーにならない(client: AsyncClient):
    """停止は異常ではなく通常起こりうる状態なので、正常なレスポンスを返す。"""
    response = await client.get("/api/status")

    assert response.status_code == 200
    body = response.json()
    assert body["fddemu_running"] is False
    assert body["drives"] == []
    assert body["message"]


async def test_fddemu_の起動と停止(client: AsyncClient):
    started = await client.post("/api/fddemu/start", json={})
    assert started.status_code == 200
    assert started.json()["fddemu_running"] is True
    assert len(started.json()["drives"]) == 2

    stopped = await client.post("/api/fddemu/stop")
    assert stopped.status_code == 200
    assert stopped.json()["fddemu_running"] is False


async def test_挿入とイジェクト(running_client: AsyncClient):
    inserted = await running_client.post("/api/drives/0/insert", json={"path": "disk1.fdx"})
    assert inserted.status_code == 200

    drive = inserted.json()["drives"][0]
    assert drive["inserted"] is True
    assert drive["image_relative"] == "disk1.fdx"

    ejected = await running_client.post("/api/drives/0/eject")
    assert ejected.json()["drives"][0]["inserted"] is False


async def test_FDX以外は挿入できない(running_client: AsyncClient):
    """先に FDX へ変換する必要があることを伝える。

    これは利用者の選択ミスであってサーバーの障害ではないので 400 を返す。
    同じ「FDX 形式ではない」条件は情報取得・属性変更でも 400 で揃えている。
    """
    response = await running_client.post("/api/drives/0/insert", json={"path": "source.d88"})
    assert response.status_code == 400
    assert "変換" in response.json()["message"]


async def test_存在しないイメージの挿入は404(running_client: AsyncClient):
    """外部で削除された場合に起こる。分かりやすいエラーを返す。"""
    response = await running_client.post("/api/drives/0/insert", json={"path": "missing.fdx"})
    assert response.status_code == 404


async def test_ライトプロテクトの切り替え(running_client: AsyncClient):
    await running_client.post("/api/drives/0/insert", json={"path": "disk1.fdx"})

    on = await running_client.post("/api/drives/0/protect", json={"enabled": True})
    assert on.json()["drives"][0]["write_protected"] is True

    off = await running_client.post("/api/drives/0/protect", json={"enabled": False})
    assert off.json()["drives"][0]["write_protected"] is False


async def test_不正なドライブ番号は拒否される(running_client: AsyncClient):
    response = await running_client.post("/api/drives/5/eject")
    assert response.status_code == 422


# --- 一覧 -------------------------------------------------------------------


async def test_ルートの一覧(client: AsyncClient):
    response = await client.get("/api/images")
    assert response.status_code == 200

    body = response.json()
    names = [entry["name"] for entry in body["entries"]]

    # ディレクトリが先、その中では自然順
    assert names[:2] == ["empty", "ゲーム"]
    assert "disk1.fdx" in names
    assert "readme.txt" in names


async def test_種別が判定される(client: AsyncClient):
    body = (await client.get("/api/images")).json()
    kinds = {entry["name"]: entry["kind"] for entry in body["entries"]}

    assert kinds["disk1.fdx"] == "fdx"
    assert kinds["source.d88"] == "convertible_image"
    assert kinds["readme.txt"] == "unsupported"
    assert kinds["ゲーム"] == "directory"


async def test_サイズと更新日時が含まれる(client: AsyncClient):
    body = (await client.get("/api/images")).json()
    entry = next(e for e in body["entries"] if e["name"] == "disk1.fdx")

    assert entry["size"] > 0
    # UTC の ISO8601 で返す（表示のタイムゾーン変換はブラウザ側）
    assert entry["mtime"].endswith("+00:00")


async def test_複数枚組は自然順に並ぶ(client: AsyncClient):
    """辞書順だと disk1, disk10, disk2 になってしまう。"""
    body = (await client.get("/api/images", params={"path": "ゲーム"})).json()
    names = [e["name"] for e in body["entries"] if e["kind"] == "fdx"]

    assert names == ["disk1.fdx", "disk2.fdx", "disk10.fdx"]


async def test_一覧は1階層分だけ返す(client: AsyncClient):
    """ツリーは展開のたびに取得するため、再帰的に読まない。"""
    body = (await client.get("/api/images", params={"path": "ゲーム"})).json()
    names = [e["name"] for e in body["entries"]]

    assert "sub" in names
    assert "nested.fdx" not in names


async def test_挿入中のイメージに印が付く(running_client: AsyncClient):
    await running_client.post("/api/drives/1/insert", json={"path": "disk1.fdx"})

    body = (await running_client.get("/api/images")).json()
    entry = next(e for e in body["entries"] if e["name"] == "disk1.fdx")

    assert entry["mounted_on"] == [1]


async def test_ルート外の一覧は拒否される(client: AsyncClient):
    for attack in ["../", "../../etc", "/etc"]:
        response = await client.get("/api/images", params={"path": attack})
        assert response.status_code == 400, attack


async def test_存在しないフォルダは404(client: AsyncClient):
    response = await client.get("/api/images", params={"path": "missing"})
    assert response.status_code == 404
