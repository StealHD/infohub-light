from scripts.service_api_smoke import build_report, run_smoke_checks


class FakeClient:
    def __init__(self):
        self.calls = []

    def data(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/api/auth/login":
            return {"authenticated": True}
        if path == "/api/auth/status":
            return {"authenticated": True, "user": {"username": "owner"}}
        if path == "/api/config":
            return {"config": {}, "service": {"current_user": {"username": "owner"}}}
        if path == "/api/dashboard/summary":
            return {"source_count": 0, "subscription_count": 0}
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
        if path == "/api/me/items/rss%3Aitem%3A1/feedback":
            return {"article_id": "rss:item:1", "feedback_type": "not_relevant"}
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
    assert any(check["name"] == "create_private_source" for check in report["checks"])
    assert any(check["name"] == "source_test_job" for check in report["checks"])
    assert any(check["name"] == "item_feedback" for check in report["checks"])


def test_service_api_smoke_report_marks_failed_checks():
    report = build_report(
        [
            {"name": "login", "ok": True},
            {"name": "catalog_sources", "ok": False, "error": {"code": "unauthorized"}},
        ]
    )

    assert report["ok"] is False
    assert report["failed"] == ["catalog_sources"]
