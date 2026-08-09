import stat

from scripts.service_api_smoke import build_report, run_smoke_checks, write_report


class FakeClient:
    def __init__(self):
        self.calls = []
        self.users = [
            {
                "id": "usr_owner",
                "username": "owner",
                "role": "owner",
                "display_name": "Owner",
                "enabled": True,
            }
        ]

    def data(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/api/auth/login":
            return {"authenticated": True}
        if path == "/api/auth/status":
            return {"authenticated": True, "user": {"username": "owner", "role": "owner"}}
        if path == "/api/config":
            return {"config": {}, "service": {"current_user": {"username": "owner"}}}
        if path == "/api/dashboard/summary":
            return {"source_count": 0, "subscription_count": 0}
        if path == "/api/users":
            if method == "GET":
                return {"users": list(self.users)}
            user = {
                "id": "usr_smoke",
                "username": body["username"],
                "role": body["role"],
                "display_name": body["display_name"],
                "enabled": body["enabled"],
            }
            self.users.append(user)
            return user
        if path == "/api/users/usr_smoke":
            assert method == "PATCH"
            self.users[-1] = {**self.users[-1], **{k: v for k, v in body.items() if k != "password"}}
            return self.users[-1]
        if path == "/api/catalog/sources":
            if method == "GET":
                return {"sources": []}
            return {
                "id": "src_smoke",
                "type": body["type"],
                "scope": body["scope"],
                "display_name": body["display_name"],
            }
        if path == "/api/feed/latest":
            return {"scope": "user", "items": [{"id": "rss:item:1"}]}
        if path == "/api/jobs":
            return {"jobs": []}
        if path == "/api/catalog/sources/src_smoke/subscribe":
            return {"subscription": {"id": "sub_smoke", "source_id": "src_smoke"}}
        if path == "/api/jobs/source-test":
            return {"id": "job_smoke", "status": "queued", "job_type": "source_test"}
        if path == "/api/me/item-state?article_ids=rss%3Aitem%3A1":
            return {"states": {"rss:item:1": {"is_read": False}}}
        if path == "/api/me/items/rss%3Aitem%3A1/state":
            return {"article_id": "rss:item:1", "is_read": True}
        raise AssertionError(f"unexpected call: {method} {path}")


def test_service_api_smoke_read_mode_uses_safe_core_endpoints():
    client = FakeClient()

    report = run_smoke_checks(
        client,
        username="owner",
        password="secret-password",
        mutating=False,
    )

    assert report["ok"] is True
    assert [check["name"] for check in report["checks"]] == [
        "login",
        "auth_status",
        "config",
        "dashboard",
        "users",
        "catalog_sources",
        "feed_latest",
        "jobs",
    ]
    assert ("POST", "/api/catalog/sources", None) not in client.calls


def test_service_api_smoke_mutating_mode_creates_private_source_job_and_item_state():
    client = FakeClient()

    report = run_smoke_checks(
        client,
        username="owner",
        password="secret-password",
        mutating=True,
    )

    assert report["ok"] is True
    assert any(check["name"] == "create_smoke_member" for check in report["checks"])
    assert any(check["name"] == "patch_smoke_member" for check in report["checks"])
    assert any(check["name"] == "create_private_source" for check in report["checks"])
    assert any(check["name"] == "source_test_job" for check in report["checks"])
    assert any(check["name"] == "item_state_update" for check in report["checks"])


def test_service_api_smoke_report_marks_failed_checks():
    report = build_report(
        [
            {"name": "login", "ok": True},
            {"name": "catalog_sources", "ok": False, "error": {"code": "unauthorized"}},
        ]
    )

    assert report["ok"] is False
    assert report["failed"] == ["catalog_sources"]


def test_service_api_smoke_report_file_is_private(tmp_path):
    output = tmp_path / "api-smoke.json"

    write_report(build_report([]), str(output))

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
