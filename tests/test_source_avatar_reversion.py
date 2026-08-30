from src.services.media_cache import MediaCacheService
from src.storage.service_store import ServiceStore


def test_source_avatar_can_return_to_a_previous_remote_identity(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="X profile",
        config={"platform": "x", "kind": "profile", "target": "profile"},
    )
    fetched: list[str] = []

    def fetch_image(url: str) -> tuple[bytes, str]:
        fetched.append(url)
        version = b"previous" if "previous-avatar" in url else b"current"
        return b"\x89PNG\r\n\x1a\n" + version, "image/png"

    cache = MediaCacheService(store, data_dir=tmp_path, fetch_image=fetch_image)
    urls = (
        "https://pbs.twimg.com/previous-avatar.png",
        "https://pbs.twimg.com/current-avatar.png",
        "https://pbs.twimg.com/previous-avatar.png",
    )
    versions = []
    paths = []
    for url in urls:
        result = cache.cache_source_avatar_candidates(
            workspace_id=workspace["id"],
            source_id=source_id,
            remote_urls=[url],
        )
        assert result["status"] == "stored"
        version = cache.avatar_for_source(
            workspace_id=workspace["id"], source_id=source_id
        )
        versions.append(version)
        paths.append(tmp_path / version["local_path"])

    assert fetched == list(urls)
    assert len({version["id"] for version in versions}) == 3
    assert versions[2]["checksum"] == versions[0]["checksum"]
    assert versions[2]["remote_url"] == urls[2]
    assert not paths[0].exists()
    assert not paths[1].exists()
    assert paths[2].is_file()
    assert store.connect().execute(
        """SELECT COUNT(*) FROM media_assets
           WHERE source_id = ? AND asset_kind = 'source_avatar'""",
        (source_id,),
    ).fetchone()[0] == 1
