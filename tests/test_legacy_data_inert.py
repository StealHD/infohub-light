import hashlib

from src.api.server import create_app
from src.services.feed_read import FeedReadService


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_service_start_and_feed_reads_leave_legacy_runtime_data_untouched(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    data_dir = tmp_path / "data"
    site_dir = data_dir / "site"
    site_dir.mkdir(parents=True)
    site_payload = site_dir / "radar-data.json"
    legacy_db = data_dir / "horizon.db"
    site_payload.write_bytes(b'legacy-site-sentinel\n')
    legacy_db.write_bytes(b'legacy-sqlite-sentinel\n')
    before = {_path: _digest(_path) for _path in (site_payload, legacy_db)}

    app = create_app(data_dir=data_dir, static_dir=tmp_path / "missing-react")
    store = app.state.service_store
    user = store.get_user_by_username("owner")
    FeedReadService(store).latest_feed(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
    )

    assert {_path: _digest(_path) for _path in before} == before
