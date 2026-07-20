from scripts.service_ui_smoke import build_report, run_ui_smoke


class FakeClient:
    def __init__(self, fail_login=False, empty_feed=False):
        self.calls = []
        self.fail_login = fail_login
        self.empty_feed = empty_feed

    def data(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/api/auth/login":
            if self.fail_login:
                raise RuntimeError("bad credentials")
            return {"authenticated": True}
        if path == "/api/auth/status":
            return {"authenticated": True, "user": {"username": "owner", "role": "owner"}}
        if path == "/api/feed/latest":
            return {"scope": "user", "items": [] if self.empty_feed else [{"id": "rss:item:1"}]}
        if path == "/api/catalog/sources":
            if method == "GET":
                return {"sources": []}
            return {"id": "src_ui_smoke", "scope": "private", "type": "rss"}
        if path == "/api/catalog/sources/src_ui_smoke/subscribe":
            return {"subscription": {"id": "sub_ui_smoke"}}
        if path == "/api/jobs/source-test":
            return {"id": "job_ui_smoke", "status": "queued"}
        if path == "/api/me/item-state?article_ids=rss%3Aitem%3A1":
            return {"states": {"rss:item:1": {"is_read": False}}}
        if path == "/api/me/items/rss%3Aitem%3A1/state":
            return {"article_id": "rss:item:1", "is_read": True}
        if path == "/api/me/items/rss%3Aitem%3A1/feedback":
            return {"article_id": "rss:item:1", "feedback_type": "not_relevant"}
        raise AssertionError(f"unexpected call: {method} {path}")


def _fetcher(path):
    assets = {
        "/": """
          <button data-view="subscriptions">订阅</button>
          <button data-view="config">配置</button>
          <section id="readerPanel"></section>
          <form id="authLoginForm"></form>
          <script src="./auth.js?v=1"></script>
          <script src="./app.js?v=1"></script>
          <script src="./subscriptions.js?v=1"></script>
        """,
        "/auth.js": "fetch('/api/auth/status'); fetch('/api/auth/login'); fetch('/api/auth/logout');",
        "/app.js": "fetch('/api/feed/latest?ts=1');",
        "/subscriptions.js": "fetch('/api/catalog/sources'); fetch('/api/jobs/source-test');",
    }
    if path not in assets:
        raise RuntimeError(f"missing asset {path}")
    return assets[path]


def test_ui_smoke_read_mode_checks_page_assets_and_safe_api_calls():
    client = FakeClient()

    report = run_ui_smoke(
        client,
        base_url="http://127.0.0.1:8080",
        username="owner",
        password="secret-password",
        fetch_text=_fetcher,
        mutating=False,
    )

    assert report["ok"] is True
    assert [check["name"] for check in report["checks"]] == [
        "login",
        "auth_status",
        "fetch_index",
        "static_entrypoints",
        "local_json_references",
        "feed_latest",
    ]
    assert ("POST", "/api/catalog/sources", None) not in client.calls


def test_ui_smoke_marks_login_failure():
    report = run_ui_smoke(
        FakeClient(fail_login=True),
        base_url="http://127.0.0.1:8080",
        username="owner",
        password="wrong-password",
        fetch_text=_fetcher,
        mutating=False,
    )

    assert report["ok"] is False
    assert report["failed"] == ["login"]


def test_ui_smoke_fails_when_static_js_references_local_json():
    def bad_fetcher(path):
        if path == "/":
            return """
              <button data-view="subscriptions">订阅</button>
              <button data-view="config">配置</button>
              <section id="readerPanel"></section>
              <form id="authLoginForm"></form>
              <script src="./auth.js?v=1"></script>
              <script src="./app.js?v=1"></script>
              <script src="./subscriptions.js?v=1"></script>
            """
        if path == "/auth.js":
            return "fetch('/api/auth/status')"
        if path == "/app.js":
            return "fetch('./radar-data.json?ts=1')"
        if path == "/subscriptions.js":
            return "fetch('/api/catalog/sources')"
        raise RuntimeError(path)

    report = run_ui_smoke(
        FakeClient(),
        base_url="http://127.0.0.1:8080",
        username="owner",
        password="secret-password",
        fetch_text=bad_fetcher,
        mutating=False,
    )

    assert report["ok"] is False
    assert "local_json_references" in report["failed"]


def test_ui_smoke_mutating_mode_creates_source_job_and_item_state():
    client = FakeClient()

    report = run_ui_smoke(
        client,
        base_url="http://127.0.0.1:8080",
        username="owner",
        password="secret-password",
        fetch_text=_fetcher,
        mutating=True,
    )

    assert report["ok"] is True
    assert any(check["name"] == "create_private_source" for check in report["checks"])
    assert any(check["name"] == "source_test_job" for check in report["checks"])
    assert any(check["name"] == "item_feedback" for check in report["checks"])


def test_build_report_collects_failed_checks():
    report = build_report(
        [
            {"name": "login", "ok": True},
            {"name": "static_entrypoints", "ok": False, "error": {"code": "missing_entry"}},
        ]
    )

    assert report["ok"] is False
    assert report["failed"] == ["static_entrypoints"]
