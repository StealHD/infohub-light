import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.models import ApifySocialConfig, ApifySocialSubscriptionConfig, SourceType
from src.scrapers.apify_client import (
    ApifyActorRunResult,
    ApifyClient,
    ApifyClientError,
    ApifyCredentialFailureKind,
    ApifyCredentialLease,
)
from src.scrapers.apify_social import (
    ApifySocialScraper,
    ApifySocialSemanticError,
)


def _run_resp(run_id="run1", dataset_id="ds1"):
    return {"data": {"id": run_id, "defaultDatasetId": dataset_id}}


def _status_resp(status="SUCCEEDED"):
    return {"data": {"status": status}}


def _social_config(*subscriptions, **kwargs):
    defaults = {
        "enabled": True,
        "token_env": "APIFY_TOKEN",
        "timeout_seconds": 5,
        "actors": {
            "x": {"actor_id": "xquik/x-tweet-scraper"},
            "instagram": {"actor_id": "apify/instagram-api-scraper"},
            "facebook": {"actor_id": "whoareyouanas/facebook-group-scraper"},
            "telegram": {"actor_id": "thescrapelab/apify-telegram-scraper"},
        },
        "subscriptions": list(subscriptions),
    }
    defaults.update(kwargs)
    return ApifySocialConfig(**defaults)


def _sub(platform, kind, target, **kwargs):
    defaults = {
        "platform": platform,
        "kind": kind,
        "target": target,
        "fetch_limit": 3,
        "enabled": True,
        "tags": ["行业动态"],
    }
    defaults.update(kwargs)
    return ApifySocialSubscriptionConfig(**defaults)


def test_x_profile_actor_inputs_match_published_contracts():
    scraper = ApifySocialScraper(
        _social_config(_sub("x", "profile", "@openai", fetch_limit=7)),
        httpx.AsyncClient(),
    )
    sub = scraper.social_config.subscriptions[0]

    assert scraper._actor_input(
        sub,
        actor_id="scrape.badger/twitter-tweets-scraper",
    ) == {
        "mode": "Advanced Search",
        "query": "from:openai",
        "query_type": "Latest",
        "max_results": 7,
    }
    assert scraper._actor_input(
        sub,
        actor_id="dami_studio/tweet-scraper",
    ) == {
        "twitterHandles": ["openai"],
        "maxItems": 7,
        "includeReplies": False,
    }
    assert scraper._actor_input(
        sub,
        actor_id="xquik/x-tweet-scraper",
    ) == {
        "twitterHandles": ["openai"],
        "maxItems": 7,
    }
    asyncio.run(scraper.client.aclose())


def test_paid_canary_caps_every_x_actor_contract_to_one_item():
    scraper = ApifySocialScraper(
        _social_config(_sub("x", "profile", "@openai", fetch_limit=50)),
        httpx.AsyncClient(),
        paid_canary=True,
    )
    sub = scraper.social_config.subscriptions[0]

    assert scraper._actor_input(
        sub,
        actor_id="scrape.badger/twitter-tweets-scraper",
    )["max_results"] == 1
    assert scraper._actor_input(
        sub,
        actor_id="dami_studio/tweet-scraper",
    )["maxItems"] == 1
    assert scraper._actor_input(
        sub,
        actor_id="xquik/x-tweet-scraper",
    )["maxItems"] == 1
    asyncio.run(scraper.client.aclose())


def test_routed_x_profile_rejects_dami_error_rows_with_charge(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    scraper = ApifySocialScraper(
        _social_config(_sub("x", "profile", "missing")),
        httpx.AsyncClient(),
    )

    async def fake_run_actor_detailed(*_args, **_kwargs):
        return ApifyActorRunResult(
            items=[{"errorCode": "NOT_FOUND", "message": "not found"}],
            actual_charge_usd=0.004,
            cost_final=True,
        )

    monkeypatch.setattr(
        ApifyClient,
        "run_actor_detailed",
        fake_run_actor_detailed,
    )
    with pytest.raises(ApifySocialSemanticError) as exc_info:
        asyncio.run(
            scraper.fetch_x_profile_with_actor(
                scraper.social_config.subscriptions[0],
                datetime.now(timezone.utc) - timedelta(hours=1),
                actor_id="dami_studio/tweet-scraper",
                logical_run_id="attempt-safe-id",
            )
        )
    asyncio.run(scraper.client.aclose())

    assert exc_info.value.code == "apify_actor_target_unavailable"
    assert exc_info.value.failure_scope == "target"
    assert exc_info.value.actual_charge_usd == 0.004
    assert exc_info.value.cost_final is True


@pytest.mark.parametrize(
    "row",
    [
        {
            "id": "tweet-shaped-demo",
            "text": "looks real",
            "createdAt": "2030-01-01T00:00:00Z",
            "demo": True,
            "errorCode": "PRIVATE",
        },
        {
            "id": "tweet-shaped-paywall",
            "text": "upgrade",
            "createdAt": "2030-01-01T00:00:00Z",
            "paymentRequired": True,
        },
        {"noResults": True, "demo": True},
        {"noResults": True, "resultType": "diagnostic"},
    ],
)
def test_x_semantic_validation_never_accepts_tweet_shaped_control_rows(row):
    scraper = object.__new__(ApifySocialScraper)

    with pytest.raises(ApifySocialSemanticError) as exc_info:
        scraper._validated_x_rows([row])

    assert exc_info.value.code == "apify_actor_placeholder"
    assert exc_info.value.failure_scope == "actor"


def test_x_semantic_validation_keeps_only_genuine_rows_from_mixed_dataset():
    scraper = object.__new__(ApifySocialScraper)
    genuine = {
        "id": "real-post",
        "text": "real",
        "createdAt": "2030-01-01T00:00:00Z",
    }
    placeholder = {
        "id": "fake-post",
        "text": "demo",
        "createdAt": "2030-01-01T00:00:00Z",
        "resultType": "paywall",
    }

    rows, outcome = scraper._validated_x_rows([placeholder, genuine])

    assert rows == [genuine]
    assert outcome == "valid_nonempty"


def test_x_semantic_validation_distinguishes_raw_empty_from_explicit_no_results():
    scraper = object.__new__(ApifySocialScraper)

    assert scraper._validated_x_rows([]) == ([], "suspicious_empty")
    assert scraper._validated_x_rows([{"noResults": True}]) == (
        [],
        "valid_empty",
    )


def test_apify_client_detailed_result_captures_terminal_usage():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(
                200,
                json={"data": {"status": "SUCCEEDED", "usageTotalUsd": 0.006}},
            )
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[{"id": "tweet-1"}])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        ApifyClient(
            token="test-token",
            http_client=http_client,
            poll_interval=0,
        ).run_actor_detailed(
            "actor/id",
            {},
            max_total_charge_usd=0.02,
        )
    )
    asyncio.run(http_client.aclose())

    assert result.items == [{"id": "tweet-1"}]
    assert result.actual_charge_usd == 0.006
    assert result.cost_final is True


def test_apify_client_resumes_terminal_dataset_with_get_only():
    lease = ApifyCredentialLease(
        secret_id="secret-one",
        secret_version=1,
        pool_generation=1,
        env_name="APIFY_TOKEN",
        reservation_id="ledger-run",
        token="token-one",
    )

    class _ResumeCoordinator:
        completed = False

        def lease_for_run(self, reservation_id):
            assert reservation_id == "ledger-run"
            return lease

        def get_run(self, reservation_id):
            assert reservation_id == "ledger-run"
            return {
                "id": "ledger-run",
                "remote_run_id": "remote-run",
                "dataset_id": "dataset-one",
                "status": "succeeded",
                "charge_actual_usd": 0.005,
                "charge_final": 1,
            }

        def complete_run_reconciliation(self, completed_lease):
            assert completed_lease == lease
            self.completed = True

    coordinator = _ResumeCoordinator()
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        assert request.headers["Authorization"] == "Bearer token-one"
        return httpx.Response(200, json=[{"id": "tweet-one"}])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        ApifyClient(
            coordinator=coordinator,
            http_client=client,
            retry_base_delay=0,
        ).resume_actor_detailed("ledger-run")
    )
    asyncio.run(client.aclose())

    assert result.items == [{"id": "tweet-one"}]
    assert result.actual_charge_usd == 0.005
    assert result.cost_final is True
    assert requests == [("GET", "/v2/datasets/dataset-one/items")]
    assert coordinator.completed is True


def test_apify_client_resume_poll_parse_failure_stays_reconcilable():
    lease = ApifyCredentialLease(
        secret_id="secret-one",
        secret_version=1,
        pool_generation=1,
        env_name="APIFY_TOKEN",
        reservation_id="ledger-run",
        token="token-one",
    )

    class _ResumeCoordinator:
        blocked = False

        def lease_for_run(self, _reservation_id):
            return lease

        def get_run(self, _reservation_id):
            return {
                "id": "ledger-run",
                "remote_run_id": "remote-run",
                "dataset_id": "dataset-one",
                "status": "running",
            }

        def block_run_reconciliation(self, blocked_lease, _error_code):
            assert blocked_lease == lease
            self.blocked = True

    coordinator = _ResumeCoordinator()
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        return httpx.Response(200, content=b"not-json")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ApifyClientError) as raised:
        asyncio.run(
            ApifyClient(
                coordinator=coordinator,
                http_client=client,
                poll_interval=0,
                retry_base_delay=0,
            ).resume_actor_detailed("ledger-run")
        )
    asyncio.run(client.aclose())

    assert raised.value.code == "apify_run_reconcile_required"
    assert requests == [("GET", "/v2/actor-runs/remote-run")]
    assert coordinator.blocked is True


def test_apify_client_invalid_poll_response_aborts_before_any_new_post():
    requests = []
    abort_polled = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal abort_polled
        requests.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/abort"):
            return httpx.Response(
                200,
                json={"data": {"status": "ABORTING"}},
            )
        if request.method == "POST":
            return httpx.Response(
                200,
                json=_run_resp("run-one", "dataset-one"),
            )
        if request.url.path.endswith("/run-one"):
            if not abort_polled:
                abort_polled = True
                return httpx.Response(200, content=b"not-json")
            return httpx.Response(
                200,
                json={"data": {"status": "ABORTED"}},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ApifyClientError) as raised:
        asyncio.run(
            ApifyClient(
                tokens=[
                    ("APIFY_TOKEN", "token-one"),
                    ("APIFY_TOKEN_2", "token-two"),
                ],
                http_client=client,
                poll_interval=0,
                retry_base_delay=0,
            ).run_actor("actor/id", {})
        )
    asyncio.run(client.aclose())

    assert raised.value.code == "apify_run_status_unavailable"
    starts = [
        request
        for request in requests
        if request[0] == "POST" and request[1].endswith("/actor~id/runs")
    ]
    assert starts == [("POST", "/v2/acts/actor~id/runs")]


class _FakeDrainPendingError(RuntimeError):
    code = "apify_key_drain_pending"


class _FakeApifyCoordinator:
    def __init__(
        self,
        *credentials: tuple[str, str],
        quota_check_required: bool = False,
    ):
        self.credentials = list(credentials)
        self.quota_check_required = quota_check_required
        self.current_index = 0
        self.reservation_index = 0
        self.draining = False
        self.blocked = False
        self.events = []
        self.active_runs = {}
        self.logical_run_ids = []

    def acquire_credential(
        self,
        attempted_secret_ids=(),
        *,
        logical_run_id=None,
    ):
        secret_id, token = self.credentials[self.current_index]
        if secret_id in attempted_secret_ids:
            raise RuntimeError("credential already attempted")
        self.reservation_index += 1
        lease = ApifyCredentialLease(
            secret_id=secret_id,
            secret_version=1,
            pool_generation=self.current_index,
            env_name=f"{secret_id.upper()}_ENV",
            reservation_id=f"reservation-{self.reservation_index}",
            token=token,
            quota_check_required=self.quota_check_required,
        )
        self.events.append(("acquire", lease.secret_id, lease.reservation_id))
        self.logical_run_ids.append(logical_run_id)
        return lease

    def record_quota_snapshot(self, lease, **snapshot):
        self.events.append(
            (
                "quota",
                lease.secret_id,
                snapshot["remaining_included_credits_usd"],
            )
        )

    def assert_lease_startable(self, lease):
        if self.draining or lease.pool_generation != self.current_index:
            raise _FakeDrainPendingError()

    def register_run(
        self,
        lease,
        remote_run_id,
        dataset_id,
        logical_run_id=None,
    ):
        self.active_runs[lease.reservation_id] = (
            lease,
            remote_run_id,
            dataset_id,
        )
        self.events.append(
            ("register", lease.secret_id, remote_run_id, logical_run_id)
        )

    def mark_run_aborting(self, lease, remote_run_id):
        self.events.append(("aborting", lease.secret_id, remote_run_id))

    def mark_run_terminal(self, lease, remote_run_id, status):
        self.events.append(
            ("terminal", lease.secret_id, remote_run_id, status.upper())
        )
        self.active_runs.pop(lease.reservation_id, None)

    def should_retry_after_terminal(self, lease, _remote_run_id, _status):
        if self.draining:
            return None
        return lease.pool_generation != self.current_index

    async def report_credential_failure(
        self,
        lease,
        *,
        failure_kind,
        status_code,
        error_type,
        abort_run,
    ):
        self.draining = True
        self.events.append(
            (
                "credential_failure",
                lease.secret_id,
                failure_kind,
                status_code,
                error_type,
            )
        )
        runs = [
            active
            for active in self.active_runs.values()
            if active[0].pool_generation <= lease.pool_generation
        ]
        for run_lease, remote_run_id, _dataset_id in runs:
            await abort_run(run_lease, remote_run_id)
        self.current_index += 1
        self.draining = False

    def report_start_outcome_unknown(
        self,
        lease,
        error_code="apify_start_outcome_unknown",
    ):
        self.blocked = True
        self.events.append(("start_unknown", lease.secret_id, error_code))

    def block_run_reconciliation(
        self,
        lease,
        error_code="apify_run_reconcile_required",
    ):
        self.blocked = True
        self.events.append(("run_reconcile", lease.secret_id, error_code))

    def release_reservation(self, lease, error_code):
        self.events.append(("release", lease.secret_id, error_code))
        self.active_runs.pop(lease.reservation_id, None)


def test_apify_social_defaults_to_single_item_capable_x_actor():
    assert ApifySocialConfig().actors.x.actor_id == "xquik/x-tweet-scraper"


def test_apify_client_runs_actor_with_bearer_token_and_fetches_dataset():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer test-token"
        if request.method == "POST" and request.url.path == "/v2/acts/apify~instagram-api-scraper/runs":
            assert json.loads(request.content) == {"directUrls": ["https://instagram.com/openai"]}
            return httpx.Response(200, json=_run_resp())
        if request.method == "GET" and request.url.path == "/v2/actor-runs/run1":
            return httpx.Response(200, json=_status_resp())
        if request.method == "GET" and request.url.path == "/v2/datasets/ds1/items":
            assert request.url.params["clean"] == "true"
            return httpx.Response(200, json=[{"id": "item1"}])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        ApifyClient(
            token="test-token",
            http_client=client,
            poll_interval=0,
            timeout_seconds=5,
            retry_base_delay=0,
        ).run_actor("apify/instagram-api-scraper", {"directUrls": ["https://instagram.com/openai"]})
    )
    asyncio.run(client.aclose())

    assert result == [{"id": "item1"}]
    assert [request.method for request in requests] == ["POST", "GET", "GET"]


def test_apify_terminal_error_does_not_expose_remote_identifiers():
    remote_run_id = "remote-run-private"
    remote_dataset_id = "remote-dataset-private"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200,
                json=_run_resp(remote_run_id, remote_dataset_id),
            )
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp("FAILED"))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApifyClientError) as raised:
            asyncio.run(
                ApifyClient(
                    token="test-token",
                    http_client=client,
                    poll_interval=0,
                ).run_actor("actor/id", {})
            )
    finally:
        asyncio.run(client.aclose())

    assert raised.value.code == "apify_run_status_unavailable"
    assert remote_run_id not in str(raised.value)
    assert remote_dataset_id not in str(raised.value)


def test_apify_timeout_error_does_not_expose_remote_identifiers():
    remote_run_id = "remote-run-timeout-private"
    remote_dataset_id = "remote-dataset-timeout-private"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/abort"):
            return httpx.Response(200, json=_status_resp("ABORTING"))
        if request.method == "POST":
            return httpx.Response(
                200,
                json=_run_resp(remote_run_id, remote_dataset_id),
            )
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp("ABORTED"))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(TimeoutError) as raised:
            asyncio.run(
                ApifyClient(
                    token="test-token",
                    http_client=client,
                    poll_interval=0,
                    timeout_seconds=0,
                ).run_actor("actor/id", {})
            )
    finally:
        asyncio.run(client.aclose())

    assert remote_run_id not in str(raised.value)
    assert remote_dataset_id not in str(raised.value)


def test_apify_client_does_not_retry_non_idempotent_start_on_rate_limit():
    attempts = {"post": 0}
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers["Authorization"])
        if request.method == "POST":
            attempts["post"] += 1
            return httpx.Response(429, json={"error": {"message": "rate limit"}})
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ApifyClientError) as raised:
        asyncio.run(
            ApifyClient(
                tokens=[
                    ("APIFY_TOKEN", "test-token"),
                    ("APIFY_TOKEN_2", "unused-token"),
                ],
                http_client=client,
                poll_interval=0,
                timeout_seconds=5,
                retry_base_delay=0,
            ).run_actor_detailed(
                "actor/id",
                {},
                max_remote_starts=1,
            )
        )
    asyncio.run(client.aclose())

    assert raised.value.code == "apify_actor_start_rejected"
    assert attempts["post"] == 1
    assert set(seen_auth) == {"Bearer test-token"}


def test_unknown_start_callback_failure_keeps_poison_error_and_one_post():
    class BrokenUnknownCoordinator(_FakeApifyCoordinator):
        def report_start_outcome_unknown(self, *_args, **_kwargs):
            raise RuntimeError("local poison callback failed")

    coordinator = BrokenUnknownCoordinator(
        ("secret-one", "token-one"),
        ("secret-two", "token-two"),
    )
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.headers["Authorization"])
        raise httpx.ReadTimeout("unknown start", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApifyClientError) as raised:
            asyncio.run(
                ApifyClient(
                    coordinator=coordinator,
                    http_client=client,
                    retry_base_delay=0,
                ).run_actor("actor/id", {})
            )
    finally:
        asyncio.run(client.aclose())

    assert raised.value.code == "apify_start_outcome_unknown"
    assert attempts == ["Bearer token-one"]


def test_reconcile_callback_failure_keeps_known_run_poison_error():
    class BrokenReconcileCoordinator(_FakeApifyCoordinator):
        def block_run_reconciliation(self, *_args, **_kwargs):
            raise RuntimeError("local reconcile callback failed")

    coordinator = BrokenReconcileCoordinator(("secret-one", "token-one"))
    attempts = {"post": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            attempts["post"] += 1
            return httpx.Response(200, json=_run_resp("run-known", "dataset-known"))
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp("SUCCEEDED"))
        if "/datasets/" in request.url.path:
            return httpx.Response(
                401,
                json={"error": {"type": "token-not-valid"}},
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApifyClientError) as raised:
            asyncio.run(
                ApifyClient(
                    coordinator=coordinator,
                    http_client=client,
                    poll_interval=0,
                    retry_base_delay=0,
                ).run_actor("actor/id", {})
            )
    finally:
        asyncio.run(client.aclose())

    assert raised.value.code == "apify_run_reconcile_required"
    assert attempts["post"] == 1


def test_apify_client_retries_idempotent_get_5xx_on_same_actor():
    attempts = {"post": 0, "status": 0, "dataset": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            attempts["post"] += 1
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            attempts["status"] += 1
            if attempts["status"] == 1:
                return httpx.Response(503, json={"error": {"type": "temporary"}})
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            attempts["dataset"] += 1
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        ApifyClient(
            token="test-token",
            http_client=client,
            poll_interval=0,
            retry_base_delay=0,
        ).run_actor("actor/id", {})
    )
    asyncio.run(client.aclose())

    assert result == []
    assert attempts == {"post": 1, "status": 2, "dataset": 1}


def test_apify_client_retries_idempotent_get_transport_on_same_actor():
    attempts = {"post": 0, "status": 0, "dataset": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            attempts["post"] += 1
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            attempts["status"] += 1
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            attempts["dataset"] += 1
            if attempts["dataset"] == 1:
                raise httpx.ReadTimeout("temporary", request=request)
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        ApifyClient(
            token="test-token",
            http_client=client,
            poll_interval=0,
            retry_base_delay=0,
        ).run_actor("actor/id", {})
    )
    asyncio.run(client.aclose())

    assert result == []
    assert attempts == {"post": 1, "status": 1, "dataset": 2}


def test_apify_client_retries_dataset_decoding_on_same_run_with_identity_encoding():
    attempts = {"post": 0, "status": 0, "dataset": 0}
    encodings = []

    def handler(request: httpx.Request) -> httpx.Response:
        encodings.append(request.headers.get("Accept-Encoding"))
        if request.method == "POST":
            attempts["post"] += 1
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            attempts["status"] += 1
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            attempts["dataset"] += 1
            if attempts["dataset"] == 1:
                raise httpx.DecodingError(
                    "brotli: decoder failed",
                    request=request,
                )
            return httpx.Response(200, json=[{"id": "tweet-one"}])
        raise AssertionError(f"Unexpected request: {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        ApifyClient(
            token="test-token",
            http_client=client,
            poll_interval=0,
            retry_base_delay=0,
        ).run_actor("actor/id", {})
    )
    asyncio.run(client.aclose())

    assert result == [{"id": "tweet-one"}]
    assert attempts == {"post": 1, "status": 1, "dataset": 2}
    assert encodings == ["identity"] * 4


def test_apify_client_rotates_to_next_token_on_quota_failure():
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers["Authorization"])
        if request.method == "POST" and request.headers["Authorization"] == "Bearer token-one":
            return httpx.Response(
                402,
                json={"error": {"message": "monthly usage quota exceeded"}},
            )
        if request.method == "POST":
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[{"id": "ok"}])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        ApifyClient(
            tokens=[("APIFY_TOKEN", "token-one"), ("APIFY_TOKEN_2", "token-two")],
            http_client=client,
            poll_interval=0,
            timeout_seconds=5,
            retry_base_delay=0,
        ).run_actor("actor/id", {})
    )
    asyncio.run(client.aclose())

    assert result == [{"id": "ok"}]
    assert seen_auth == [
        "Bearer token-one",
        "Bearer token-two",
        "Bearer token-two",
        "Bearer token-two",
    ]


def test_legacy_poll_402_never_starts_a_second_paid_run():
    requests = []
    old_poll_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal old_poll_count
        auth = request.headers["Authorization"]
        requests.append((request.method, request.url.path, auth, dict(request.url.params)))
        if request.method == "POST" and request.url.path.endswith("/abort"):
            assert request.url.params["gracefully"] == "false"
            assert auth == "Bearer token-one"
            return httpx.Response(200, json=_status_resp("ABORTING"))
        if request.method == "POST" and auth == "Bearer token-one":
            return httpx.Response(200, json=_run_resp("run-old", "dataset-old"))
        if request.method == "GET" and request.url.path.endswith("/run-old"):
            old_poll_count += 1
            if old_poll_count == 1:
                return httpx.Response(
                    402,
                    json={"error": {"type": "monthly-usage-limit-exceeded"}},
                )
            return httpx.Response(200, json=_status_resp("ABORTED"))
        if request.method == "POST" and auth == "Bearer token-two":
            return httpx.Response(200, json=_run_resp("run-new", "dataset-new"))
        if request.method == "GET" and request.url.path.endswith("/run-new"):
            return httpx.Response(200, json=_status_resp())
        if request.url.path.endswith("/dataset-new/items"):
            return httpx.Response(200, json=[{"id": "new"}])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ApifyClientError) as raised:
        asyncio.run(
            ApifyClient(
                tokens=[
                    ("APIFY_TOKEN", "token-one"),
                    ("APIFY_TOKEN_2", "token-two"),
                ],
                http_client=client,
                poll_interval=0,
                retry_base_delay=0,
            ).run_actor("actor/id", {})
        )
    asyncio.run(client.aclose())

    assert raised.value.code == "apify_run_reconcile_required"
    assert [
        auth
        for method, path, auth, _params in requests
        if method == "POST" and path.endswith("/actor~id/runs")
    ] == ["Bearer token-one"]
    assert not any(auth == "Bearer token-two" for _method, _path, auth, _params in requests)


def test_apify_client_reports_all_token_failures():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "error": {
                    "type": "not-enough-usage-to-run-paid-actor",
                    "message": "account cannot start this actor",
                }
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ValueError, match="APIFY_TOKEN.*APIFY_TOKEN_2"):
            asyncio.run(
                ApifyClient(
                    tokens=[("APIFY_TOKEN", "token-one"), ("APIFY_TOKEN_2", "token-two")],
                    http_client=client,
                    poll_interval=0,
                    timeout_seconds=5,
                    retry_base_delay=0,
                ).run_actor("actor/id", {})
            )
    finally:
        asyncio.run(client.aclose())


@pytest.mark.parametrize(
    "error_type",
    ["insufficient-permissions", "credit-card-invalid"],
)
def test_apify_client_does_not_rotate_on_ordinary_forbidden(error_type):
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers["Authorization"])
        return httpx.Response(
            403,
            json={"error": {"type": error_type}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApifyClientError) as raised:
            asyncio.run(
                ApifyClient(
                    tokens=[
                        ("APIFY_TOKEN", "token-one"),
                        ("APIFY_TOKEN_2", "token-two"),
                    ],
                    http_client=client,
                    retry_base_delay=0,
                ).run_actor("actor/id", {})
            )
    finally:
        asyncio.run(client.aclose())

    assert raised.value.code == "apify_actor_start_rejected"
    assert raised.value.status_code == 403
    assert seen_auth == ["Bearer token-one"]


@pytest.mark.parametrize(
    ("status_code", "expected_code"),
    [
        (404, "apify_actor_deleted"),
        (410, "apify_actor_deleted"),
        (409, "apify_actor_build_unavailable"),
        (422, "apify_actor_build_unavailable"),
    ],
)
def test_apify_client_classifies_missing_or_unbuildable_actor_without_body_leak(
    status_code,
    expected_code,
):
    private_body = "private-upstream-detail"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"error": {"message": private_body}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApifyClientError) as raised:
            asyncio.run(
                ApifyClient(
                    token="token-one",
                    http_client=client,
                    retry_base_delay=0,
                ).run_actor("actor/id", {})
            )
    finally:
        asyncio.run(client.aclose())

    assert raised.value.code == expected_code
    assert private_body not in str(raised.value)


def test_apify_client_rotates_after_invalid_token_response():
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization = request.headers["Authorization"]
        seen_auth.append(authorization)
        if authorization == "Bearer token-one":
            return httpx.Response(
                401,
                json={"error": {"type": "invalid-token"}},
            )
        if request.method == "POST":
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        ApifyClient(
            tokens=[
                ("APIFY_TOKEN", "token-one"),
                ("APIFY_TOKEN_2", "token-two"),
            ],
            http_client=client,
            poll_interval=0,
            retry_base_delay=0,
        ).run_actor("actor/id", {})
    )
    asyncio.run(client.aclose())

    assert result == []
    assert seen_auth == [
        "Bearer token-one",
        "Bearer token-two",
        "Bearer token-two",
        "Bearer token-two",
    ]


def test_apify_credential_lease_repr_hides_token():
    lease = ApifyCredentialLease(
        secret_id="secret-1",
        secret_version=2,
        pool_generation=3,
        env_name="APIFY_PRIMARY",
        reservation_id="reservation-1",
        token="private-token-must-not-appear",
    )

    assert "private-token-must-not-appear" not in repr(lease)
    assert "secret-1" in repr(lease)


def test_apify_pool_poll_402_blocks_without_failover_or_second_post():
    coordinator = _FakeApifyCoordinator(
        ("secret-one", "token-one"),
        ("secret-two", "token-two"),
    )
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers["Authorization"]
        seen_requests.append((request.method, request.url.path, auth, dict(request.url.params)))
        if request.method == "POST" and request.url.path.endswith("/abort"):
            assert request.url.params["gracefully"] == "false"
            assert auth == "Bearer token-one"
            return httpx.Response(200, json=_status_resp("ABORTING"))
        if request.method == "POST" and auth == "Bearer token-one":
            return httpx.Response(200, json=_run_resp("run-old", "dataset-old"))
        if request.method == "GET" and request.url.path.endswith("/run-old"):
            poll_count = sum(
                method == "GET" and path.endswith("/run-old")
                for method, path, _auth, _params in seen_requests
            )
            if poll_count == 1:
                return httpx.Response(
                    402,
                    json={"error": {"type": "monthly-usage-limit-exceeded"}},
                )
            return httpx.Response(200, json=_status_resp("ABORTED"))
        if request.method == "POST" and auth == "Bearer token-two":
            return httpx.Response(200, json=_run_resp("run-new", "dataset-new"))
        if request.method == "GET" and request.url.path.endswith("/run-new"):
            return httpx.Response(200, json=_status_resp())
        if request.url.path.endswith("/dataset-new/items"):
            return httpx.Response(200, json=[{"id": "from-new-key"}])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ApifyClientError) as raised:
        asyncio.run(
            ApifyClient(
                coordinator=coordinator,
                http_client=client,
                poll_interval=0,
                retry_base_delay=0,
            ).run_actor("actor/id", {})
        )
    asyncio.run(client.aclose())

    assert raised.value.code == "apify_run_reconcile_required"
    assert coordinator.blocked is True
    assert (
        "run_reconcile",
        "secret-one",
        "apify_run_reconcile_required",
    ) in coordinator.events
    assert {
        auth
        for method, path, auth, _params in seen_requests
        if method == "POST" and path.endswith("/actor~id/runs")
    } == {"Bearer token-one"}
    assert not any(auth == "Bearer token-two" for _method, _path, auth, _params in seen_requests)


def test_terminal_dataset_5xx_blocks_without_second_actor_post():
    coordinator = _FakeApifyCoordinator(
        ("secret-one", "token-one"),
        ("secret-two", "token-two"),
    )
    attempts = {"post": 0, "dataset": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            attempts["post"] += 1
            return httpx.Response(200, json=_run_resp("run-one", "dataset-one"))
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp("SUCCEEDED"))
        if "/datasets/" in request.url.path:
            attempts["dataset"] += 1
            return httpx.Response(
                503,
                json={"error": {"type": "temporarily-unavailable"}},
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApifyClientError) as raised:
            asyncio.run(
                ApifyClient(
                    coordinator=coordinator,
                    http_client=client,
                    poll_interval=0,
                    retry_base_delay=0,
                ).run_actor("actor/id", {})
            )
    finally:
        asyncio.run(client.aclose())

    assert raised.value.code == "apify_run_reconcile_required"
    assert raised.value.retryable is True
    assert attempts == {"post": 1, "dataset": 3}
    assert coordinator.blocked is True
    assert not any(
        event[0] == "credential_failure" for event in coordinator.events
    )


def test_terminal_dataset_decoding_failure_blocks_without_second_actor_post():
    coordinator = _FakeApifyCoordinator(
        ("secret-one", "token-one"),
        ("secret-two", "token-two"),
    )
    attempts = {"post": 0, "dataset": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Accept-Encoding"] == "identity"
        if request.method == "POST":
            attempts["post"] += 1
            return httpx.Response(200, json=_run_resp("run-one", "dataset-one"))
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp("SUCCEEDED"))
        if "/datasets/" in request.url.path:
            attempts["dataset"] += 1
            raise httpx.DecodingError(
                "brotli: decoder failed",
                request=request,
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApifyClientError) as raised:
            asyncio.run(
                ApifyClient(
                    coordinator=coordinator,
                    http_client=client,
                    poll_interval=0,
                    retry_base_delay=0,
                ).run_actor("actor/id", {})
            )
    finally:
        asyncio.run(client.aclose())

    assert raised.value.code == "apify_run_reconcile_required"
    assert raised.value.retryable is True
    assert attempts == {"post": 1, "dataset": 3}
    assert coordinator.blocked is True
    assert not any(
        event[0] == "credential_failure" for event in coordinator.events
    )


def test_apify_pool_unknown_start_outcome_blocks_without_trying_backup():
    coordinator = _FakeApifyCoordinator(
        ("secret-one", "token-one"),
        ("secret-two", "token-two"),
    )
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        authorization = request.headers["Authorization"]
        attempts.append(authorization)
        raise httpx.ReadTimeout(
            f"outcome unknown for {authorization}",
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApifyClientError) as raised:
            asyncio.run(
                ApifyClient(
                    coordinator=coordinator,
                    http_client=client,
                    retry_base_delay=0,
                ).run_actor(
                    "actor/id",
                    {},
                    logical_run_id="safe-source-id",
                )
            )
    finally:
        asyncio.run(client.aclose())

    assert raised.value.code == "apify_start_outcome_unknown"
    assert raised.value.retryable is False
    assert "token-one" not in str(raised.value)
    assert "token-one" not in repr(raised.value)
    assert coordinator.blocked is True
    assert attempts == ["Bearer token-one"]
    assert [
        event for event in coordinator.events if event[0] == "acquire"
    ] == [("acquire", "secret-one", "reservation-1")]
    assert coordinator.logical_run_ids == ["safe-source-id"]


def test_apify_pool_start_5xx_is_unknown_and_does_not_try_backup():
    coordinator = _FakeApifyCoordinator(
        ("secret-one", "token-one"),
        ("secret-two", "token-two"),
    )
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.headers["Authorization"])
        return httpx.Response(
            503,
            json={"error": {"type": "upstream-unavailable"}},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApifyClientError) as raised:
            asyncio.run(
                ApifyClient(
                    coordinator=coordinator,
                    http_client=client,
                    retry_base_delay=0,
                ).run_actor("actor/id", {}, logical_run_id="safe-source-id")
            )
    finally:
        asyncio.run(client.aclose())

    assert raised.value.code == "apify_start_outcome_unknown"
    assert raised.value.retryable is False
    assert coordinator.blocked is True
    assert attempts == ["Bearer token-one"]
    assert (
        "start_unknown",
        "secret-one",
        "apify_start_http_outcome_unknown",
    ) in coordinator.events


def test_apify_pool_known_run_without_dataset_is_registered_and_aborted(caplog):
    coordinator = _FakeApifyCoordinator(("secret-one", "token-one"))
    requests = []
    caplog.set_level("INFO")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/abort"):
            return httpx.Response(200, json=_status_resp("ABORTING"))
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"data": {"id": "known-run-without-dataset"}},
            )
        if request.url.path.endswith("/known-run-without-dataset"):
            return httpx.Response(200, json=_status_resp("ABORTED"))
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ApifyClientError) as raised:
            asyncio.run(
                ApifyClient(
                    coordinator=coordinator,
                    http_client=client,
                    poll_interval=0,
                ).run_actor(
                    "actor/id",
                    {},
                    logical_run_id="safe-source-id",
                )
            )
    finally:
        asyncio.run(client.aclose())

    assert raised.value.code == "apify_start_invalid_response"
    assert raised.value.retryable is True
    assert coordinator.blocked is False
    assert coordinator.active_runs == {}
    assert (
        "register",
        "secret-one",
        "known-run-without-dataset",
        "safe-source-id",
    ) in coordinator.events
    assert (
        "terminal",
        "secret-one",
        "known-run-without-dataset",
        "ABORTED",
    ) in coordinator.events
    assert requests == [
        ("POST", "/v2/acts/actor~id/runs"),
        ("POST", "/v2/actor-runs/known-run-without-dataset/abort"),
        ("GET", "/v2/actor-runs/known-run-without-dataset"),
    ]
    assert "known-run-without-dataset" not in caplog.text


def test_apify_pool_refreshes_stale_quota_before_actor_post():
    coordinator = _FakeApifyCoordinator(
        ("secret-one", "token-one"),
        quota_check_required=True,
    )
    request_paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_paths.append(request.url.path)
        assert request.headers["Authorization"] == "Bearer token-one"
        if request.url.path == "/v2/users/me":
            return httpx.Response(
                200,
                json={"data": {"plan": {"monthlyUsageCreditsUsd": 25}}},
            )
        if request.url.path == "/v2/users/me/limits":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "monthlyUsageCycle": {
                            "startAt": "2026-07-01T00:00:00Z",
                            "endAt": "2026-08-01T00:00:00Z",
                        },
                        "limits": {"maxMonthlyUsageUsd": 100},
                        "current": {"monthlyUsageUsd": 7.5},
                    }
                },
            )
        if request.method == "POST":
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        ApifyClient(
            coordinator=coordinator,
            http_client=client,
            poll_interval=0,
        ).run_actor("actor/id", {})
    )
    asyncio.run(client.aclose())

    assert result == []
    assert request_paths[:3] == [
        "/v2/users/me",
        "/v2/users/me/limits",
        "/v2/acts/actor~id/runs",
    ]
    assert ("quota", "secret-one", 17.5) in coordinator.events


def test_apify_pool_releases_pre_start_reservation_and_uses_new_generation():
    class PreStartDrainCoordinator(_FakeApifyCoordinator):
        def __init__(self):
            super().__init__(
                ("secret-one", "token-one"),
                ("secret-two", "token-two"),
            )
            self.reject_once = True

        def assert_lease_startable(self, lease):
            if self.reject_once:
                self.reject_once = False
                self.current_index = 1
                raise _FakeDrainPendingError()
            return super().assert_lease_startable(lease)

    coordinator = PreStartDrainCoordinator()
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers["Authorization"])
        if request.method == "POST":
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        ApifyClient(
            coordinator=coordinator,
            http_client=client,
            poll_interval=0,
        ).run_actor("actor/id", {})
    )
    asyncio.run(client.aclose())

    assert result == []
    assert seen_auth == [
        "Bearer token-two",
        "Bearer token-two",
        "Bearer token-two",
    ]
    assert (
        "release",
        "secret-one",
        "apify_generation_changed_before_start",
    ) in coordinator.events


def test_concurrent_started_runs_never_restart_on_new_key_after_poll_402():
    coordinator = _FakeApifyCoordinator(
        ("secret-one", "token-one"),
        ("secret-two", "token-two"),
    )
    run_counter = 0
    old_run_count = 0
    old_failure_sent = False
    statuses = {}
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal run_counter, old_run_count, old_failure_sent
        auth = request.headers["Authorization"]
        requests.append((request.method, request.url.path, auth))
        if request.method == "POST" and request.url.path.endswith("/abort"):
            run_id = request.url.path.rsplit("/", 2)[-2]
            assert auth == "Bearer token-one"
            assert request.url.params["gracefully"] == "false"
            statuses[run_id] = "ABORTED"
            return httpx.Response(200, json=_status_resp("ABORTING"))
        if request.method == "POST":
            run_counter += 1
            run_id = f"run-{run_counter}"
            dataset_id = f"dataset-{run_counter}"
            statuses[run_id] = "RUNNING" if auth == "Bearer token-one" else "SUCCEEDED"
            if auth == "Bearer token-one":
                old_run_count += 1
            return httpx.Response(200, json=_run_resp(run_id, dataset_id))
        if "/actor-runs/" in request.url.path:
            run_id = request.url.path.rsplit("/", 1)[-1]
            if (
                run_id == "run-1"
                and old_run_count >= 2
                and not old_failure_sent
            ):
                old_failure_sent = True
                return httpx.Response(
                    402,
                    json={"error": {"type": "monthly-usage-limit-exceeded"}},
                )
            if run_id != "run-1" and coordinator.blocked:
                statuses[run_id] = "SUCCEEDED"
            return httpx.Response(200, json=_status_resp(statuses[run_id]))
        if "/datasets/" in request.url.path:
            dataset_id = request.url.path.split("/")[-2]
            return httpx.Response(200, json=[{"dataset": dataset_id}])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def run_both():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as http_client:
            clients = [
                ApifyClient(
                    coordinator=coordinator,
                    http_client=http_client,
                    poll_interval=0,
                    retry_base_delay=0,
                )
                for _index in range(2)
            ]
            return await asyncio.gather(
                clients[0].run_actor("actor/id", {}),
                clients[1].run_actor("actor/id", {}),
                return_exceptions=True,
            )

    results = asyncio.run(run_both())

    failures = [item for item in results if isinstance(item, Exception)]
    successes = [item for item in results if isinstance(item, list)]
    assert len(failures) == 1
    assert getattr(failures[0], "code", None) == "apify_run_reconcile_required"
    assert [item[0]["dataset"] for item in successes] == ["dataset-2"]
    starts = [
        auth
        for method, path, auth in requests
        if method == "POST" and path.endswith("/actor~id/runs")
    ]
    assert starts == [
        "Bearer token-one",
        "Bearer token-one",
    ]
    for run_id in ("run-1", "run-2"):
        assert {
            auth for _method, path, auth in requests if run_id in path
        } == {"Bearer token-one"}


def test_apify_social_pool_mode_ignores_source_token_env_and_tracks_source_id(
    monkeypatch,
):
    monkeypatch.delenv("APIFY_SOURCE_TOKEN", raising=False)
    coordinator = _FakeApifyCoordinator(("secret-one", "pool-token"))
    now = datetime.now(timezone.utc)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer pool-token"
        if request.method == "POST":
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "tweet-pool",
                        "createdAt": now.isoformat(),
                        "fullText": "pool-backed result",
                        "author": {"userName": "OpenAI"},
                    }
                ],
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    config = _social_config(
        _sub(
            "x",
            "profile",
            "OpenAI",
            token_env="APIFY_SOURCE_TOKEN",
            source_id="source-safe-id",
        )
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    items = asyncio.run(
        ApifySocialScraper(
            config,
            client,
            apify_coordinator=coordinator,
        ).fetch(now - timedelta(hours=1))
    )
    asyncio.run(client.aclose())

    assert [item.id for item in items] == ["twitter:tweet:pool"]
    assert (
        "register",
        "secret-one",
        "run1",
        "source-safe-id",
    ) in coordinator.events


def test_apify_social_scraper_builds_platform_inputs_and_maps_items(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    seen_inputs = []

    now_iso = datetime.now(timezone.utc).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen_inputs.append((request.url.path, json.loads(request.content)))
            dataset_id = f"ds{len(seen_inputs)}"
            return httpx.Response(200, json=_run_resp(f"run{len(seen_inputs)}", dataset_id))
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if request.url.path.endswith("/ds1/items"):
            return httpx.Response(200, json=[{
                "id": "tweet-42",
                "createdAt": now_iso,
                "fullText": "OpenAI shipped a new coding agent workflow.",
                "author": {"userName": "OpenAI", "name": "OpenAI"},
                "likeCount": 12,
                "replyCount": 3,
                "retweetCount": 4,
            }])
        if request.url.path.endswith("/ds2/items"):
            return httpx.Response(200, json=[{
                "id": "ig1",
                "shortCode": "ABC123",
                "url": "https://www.instagram.com/p/ABC123/",
                "caption": "New AI product demo",
                "timestamp": now_iso,
                "ownerUsername": "openai",
            }])
        if request.url.path.endswith("/ds3/items"):
            return httpx.Response(200, json=[{
                "post_url": "https://www.facebook.com/openai/posts/123",
                "text": "OpenAI page update",
                "date": now_iso,
                "author": "OpenAI",
            }])
        if request.url.path.endswith("/ds4/items"):
            return httpx.Response(200, json=[{
                "Channel_Handle": "zaihuapd",
                "Id": 99,
                "Date": now_iso,
                "Url": "https://t.me/zaihuapd/99",
                "Body": "AI infra update",
                "LinkPreview_Url": "https://example.com/ai",
            }])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    config = _social_config(
        _sub("x", "profile", "@OpenAI"),
        _sub("instagram", "profile", "openai"),
        _sub("facebook", "page", "https://www.facebook.com/openai"),
        _sub("telegram", "channel", "https://t.me/zaihuapd"),
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    items = asyncio.run(ApifySocialScraper(config, client).fetch(since))
    asyncio.run(client.aclose())

    assert [path for path, _ in seen_inputs] == [
        "/v2/acts/xquik~x-tweet-scraper/runs",
        "/v2/acts/apify~instagram-api-scraper/runs",
        "/v2/acts/whoareyouanas~facebook-group-scraper/runs",
        "/v2/acts/thescrapelab~apify-telegram-scraper/runs",
    ]
    assert seen_inputs[0][1]["twitterHandles"] == ["OpenAI"]
    assert seen_inputs[0][1]["maxItems"] == 3
    assert seen_inputs[1][1]["directUrls"] == ["https://www.instagram.com/openai/"]
    assert seen_inputs[2][1]["startUrls"] == [{"url": "https://www.facebook.com/openai"}]
    assert seen_inputs[3][1]["channels"] == [{"channelName": "zaihuapd", "limit": 3}]

    assert [item.source_type for item in items] == [
        SourceType.TWITTER,
        SourceType.INSTAGRAM,
        SourceType.FACEBOOK,
        SourceType.TELEGRAM,
    ]
    assert [item.id for item in items] == [
        "twitter:tweet:42",
        "instagram:post:ABC123",
        "facebook:post:a9acb383d6a8",
        "telegram:zaihuapd:99",
    ]
    assert items[0].metadata["apify_platform"] == "x"
    assert items[1].metadata["tags"] == ["行业动态"]
    assert str(items[3].url) == "https://example.com/ai"


def test_x_actor_sends_exact_fetch_limit_to_upstream(
    monkeypatch,
):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    now = datetime.now(timezone.utc)
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            captured.append(json.loads(request.content))
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "tweet-new",
                        "created_at": now.isoformat(),
                        "full_text": "newest post",
                        "user": {"screen_name": "thsottiaux"},
                    },
                    {
                        "id": "tweet-older",
                        "created_at": (now - timedelta(minutes=1)).isoformat(),
                        "full_text": "older post",
                        "user": {"screen_name": "thsottiaux"},
                    },
                ],
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    config = _social_config(_sub("x", "profile", "thsottiaux", fetch_limit=1))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    items = asyncio.run(
        ApifySocialScraper(config, client).fetch(now - timedelta(hours=1))
    )
    asyncio.run(client.aclose())

    assert captured[0] == {"twitterHandles": ["thsottiaux"], "maxItems": 1}
    assert [item.id for item in items] == ["twitter:tweet:new"]


@pytest.mark.parametrize(
    "actor_id",
    [
        "scrape.badger/twitter-tweets-scraper",
        "dami_studio/tweet-scraper",
        "xquik/x-tweet-scraper",
        "apidojo/twitter-scraper-lite",
    ],
)
def test_x_actors_set_two_cent_run_charge_cap(monkeypatch, actor_id):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    seen_query = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen_query.append(dict(request.url.params))
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    asyncio.run(
        ApifySocialScraper(
            _social_config(
                _sub("x", "profile", "thsottiaux", fetch_limit=1),
                actors={"x": {"actor_id": actor_id}},
            ),
            client,
        ).fetch(datetime.now(timezone.utc) - timedelta(hours=1))
    )
    asyncio.run(client.aclose())

    assert seen_query == [
        {"maxItems": "1", "maxTotalChargeUsd": "0.02"}
    ]


def test_apify_client_pins_build_and_bounds_dataset_read():
    seen: dict[str, dict[str, str]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen["start"] = dict(request.url.params)
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            seen["dataset"] = dict(request.url.params)
            return httpx.Response(200, json=[{"id": "one"}])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = asyncio.run(
        ApifyClient(
            token="test-token",
            http_client=http_client,
            poll_interval=0,
        ).run_actor(
            "actor/id",
            {"maxItems": 1},
            build_number="1.2.3",
            max_total_charge_usd=0.02,
            dataset_item_limit=2,
        )
    )
    asyncio.run(http_client.aclose())

    assert result == [{"id": "one"}]
    assert seen == {
        "start": {
            "maxItems": "1",
            "maxTotalChargeUsd": "0.02",
            "build": "1.2.3",
        },
        "dataset": {"clean": "true", "limit": "2"},
    }


def test_apify_client_rejects_oversized_dataset_response():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[{"text": "x" * 256}])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(ApifyClientError) as raised:
        asyncio.run(
            ApifyClient(
                token="test-token",
                http_client=http_client,
                poll_interval=0,
            ).run_actor(
                "actor/id",
                {"maxItems": 1},
                build_number="1.2.3",
                dataset_response_max_bytes=64,
            )
        )
    asyncio.run(http_client.aclose())

    assert raised.value.code == "apify_dataset_response_too_large"


def test_xquik_maps_author_avatar_and_rejects_demo_only_dataset(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    now = datetime.now(timezone.utc)
    run_index = {"value": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            run_index["value"] += 1
            return httpx.Response(
                200,
                json=_run_resp(
                    f"run{run_index['value']}", f"ds{run_index['value']}"
                ),
            )
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if request.url.path.endswith("/ds1/items"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "2099999999999999999",
                        "text": "Newest real post",
                        "createdAt": now.isoformat(),
                        "url": "https://x.com/thsottiaux/status/2099999999999999999",
                        "author": {
                            "userName": "thsottiaux",
                            "name": "Tibo",
                            "profilePicture": "https://cdn.example.com/tibo.jpg",
                        },
                        "extendedEntities": {
                            "media": [{"type": "photo", "media_url_https": "https://cdn.example.com/tweet.jpg"}]
                        },
                    }
                ],
            )
        if request.url.path.endswith("/ds2/items"):
            return httpx.Response(
                200,
                json=[
                    {"resultType": "diagnostic", "status": "zero-output"},
                    {"resultType": "run-report"},
                ],
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    scraper = ApifySocialScraper(
        _social_config(_sub("x", "profile", "thsottiaux", fetch_limit=1)),
        client,
    )
    real = asyncio.run(scraper.fetch(now - timedelta(hours=1)))
    scraper.strict_errors = True
    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(scraper.fetch(now - timedelta(hours=1)))
    asyncio.run(client.aclose())

    assert real[0].id == "twitter:tweet:2099999999999999999"
    assert real[0].metadata["author_avatar_url"] == "https://cdn.example.com/tibo.jpg"
    assert real[0].metadata["media_urls"] == ["https://cdn.example.com/tweet.jpg"]
    assert real[0].metadata["media_image_count"] == 1
    assert real[0].metadata["upstream_content_format"] == "image"
    assert getattr(exc_info.value, "code", None) == "apify_demo_mode"


def test_x_flat_avatar_is_observed_before_publication_window_filter():
    client = httpx.AsyncClient()
    sub = _sub(
        "x",
        "profile",
        "thsottiaux",
        source_id="src_x_flat_avatar",
    )
    scraper = ApifySocialScraper(_social_config(sub), client)
    old = datetime.now(timezone.utc) - timedelta(days=5)

    items = scraper._parse_candidate_rows(
        [
            {
                "id": "2099999999999999999",
                "text": "Old valid post",
                "created_at": old.isoformat(),
                "user_screen_name": "thsottiaux",
                "user_profile_image_url": "https://pbs.twimg.com/profile.jpg",
            }
        ],
        sub,
        datetime.now(timezone.utc) - timedelta(hours=1),
    )
    asyncio.run(client.aclose())

    assert items == []
    assert [
        (hint.source_id, hint.origin, hint.remote_url)
        for hint in scraper.source_avatar_hints
    ] == [
        (
            "src_x_flat_avatar",
            "apify_x_profile",
            "https://pbs.twimg.com/profile.jpg",
        )
    ]


def test_apify_social_scraper_reads_token_envs_and_maps_instagram_media(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.setenv("APIFY_TOKEN_2", "backup-token")
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    now_iso = datetime.now(timezone.utc).isoformat()
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers["Authorization"])
        if request.method == "POST":
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[{
                "id": "ig1",
                "shortCode": "TSUCHA1",
                "url": "https://www.instagram.com/p/TSUCHA1/",
                "caption": "latest photo",
                "timestamp": now_iso,
                "ownerUsername": "tsucha_ri",
                "displayUrl": "https://cdn.example.com/main.jpg",
                "childPosts": [
                    {"displayUrl": "https://cdn.example.com/child.jpg"},
                ],
            }])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    config = _social_config(
        _sub("instagram", "profile", "tsucha_ri"),
        token_envs=["APIFY_TOKEN", "APIFY_TOKEN_2"],
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    items = asyncio.run(ApifySocialScraper(config, client).fetch(since))
    asyncio.run(client.aclose())

    assert items[0].metadata["image_url"] == "https://cdn.example.com/main.jpg"
    assert items[0].metadata["media_urls"] == [
        "https://cdn.example.com/main.jpg",
        "https://cdn.example.com/child.jpg",
    ]
    assert items[0].metadata["media_image_count"] == 2
    assert items[0].metadata["upstream_content_format"] == "gallery"
    assert set(seen_auth) == {"Bearer backup-token"}


def test_social_video_preview_is_not_counted_as_an_image() -> None:
    inventory = ApifySocialScraper._x_media_inventory({
        "extended_entities": {
            "media": [{
                "id": "video-1",
                "type": "video",
                "preview_image_url": "https://cdn.example.com/video-preview.jpg",
            }],
        },
    })

    assert inventory == {
        "image_urls": [],
        "image_count": 0,
        "video_count": 1,
        "audio_count": 0,
        "format": "video",
    }


def test_apify_social_scraper_uses_subscription_token_env(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "primary-token")
    monkeypatch.setenv("APIFY_TOKEN_2", "source-token")
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    now_iso = datetime.now(timezone.utc).isoformat()
    seen_auth = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers["Authorization"])
        if request.method == "POST":
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[{
                "id": "ig1",
                "shortCode": "TSUCHA1",
                "url": "https://www.instagram.com/p/TSUCHA1/",
                "caption": "latest photo",
                "timestamp": now_iso,
                "ownerUsername": "tsucha_ri",
            }])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    config = _social_config(
        _sub("instagram", "profile", "tsucha_ri", token_env="APIFY_TOKEN_2"),
        token_envs=["APIFY_TOKEN", "APIFY_TOKEN_2"],
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    items = asyncio.run(ApifySocialScraper(config, client).fetch(since))
    asyncio.run(client.aclose())

    assert [item.id for item in items] == ["instagram:post:TSUCHA1"]
    assert set(seen_auth) == {"Bearer source-token"}


def test_instagram_profile_details_fills_first_missing_avatar(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    calls = []

    async def fake_run_actor(_self, _actor_id, actor_input, **_kwargs):
        calls.append(actor_input)
        if actor_input.get("resultsType") == "details":
            return [{"username": "tsucha_ri", "profilePicUrl": "https://cdn.example.com/profile.jpg"}]
        return [{
            "id": "ig1",
            "shortCode": "TSUCHA1",
            "url": "https://www.instagram.com/p/TSUCHA1/",
            "caption": "latest photo",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ownerUsername": "tsucha_ri",
            "displayUrl": "https://cdn.example.com/post.jpg",
        }]

    monkeypatch.setattr(ApifyClient, "run_actor", fake_run_actor)
    config = _social_config(_sub(
        "instagram", "profile", "tsucha_ri", fetch_limit=1,
        fetch_profile_details=True,
    ))
    client = httpx.AsyncClient()
    items = asyncio.run(ApifySocialScraper(config, client).fetch(datetime.now(timezone.utc) - timedelta(hours=1)))
    asyncio.run(client.aclose())

    assert calls[1] == {
        "directUrls": ["https://www.instagram.com/tsucha_ri/"],
        "resultsType": "details",
        "resultsLimit": 1,
    }
    assert items[0].metadata["author_avatar_url"] == "https://cdn.example.com/profile.jpg"


def test_apify_social_scraper_returns_empty_for_stale_instagram_profile(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    old_iso = (since - timedelta(days=10)).isoformat()
    actor_starts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal actor_starts
        if request.method == "POST":
            actor_starts += 1
            return httpx.Response(200, json=_run_resp())
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[{
                "id": "ig-old",
                "shortCode": "OLDTSUCHA",
                "url": "https://www.instagram.com/p/OLDTSUCHA/",
                "caption": "older low-frequency profile post",
                "timestamp": old_iso,
                "ownerUsername": "tsucha_ri",
                "displayUrl": "https://cdn.example.com/old.jpg",
            }])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    config = _social_config(_sub(
        "instagram",
        "profile",
        "tsucha_ri",
        fetch_limit=1,
        fetch_profile_details=True,
    ))
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    items = asyncio.run(ApifySocialScraper(config, client).fetch(since))
    asyncio.run(client.aclose())

    assert items == []
    assert actor_starts == 1


def test_apify_social_stale_fallback_is_limited_to_non_x_instagram_sources():
    scraper = ApifySocialScraper

    assert scraper._should_keep_latest_when_stale(_sub("x", "profile", "OpenAI")) is False
    assert scraper._should_keep_latest_when_stale(
        _sub("instagram", "profile", "tsucha_ri")
    ) is False
    assert scraper._should_keep_latest_when_stale(
        _sub("facebook", "page", "https://facebook.com/openai")
    ) is True
    assert scraper._should_keep_latest_when_stale(
        _sub("facebook", "group", "https://facebook.com/groups/openai")
    ) is True
    assert scraper._should_keep_latest_when_stale(
        _sub("telegram", "channel", "https://t.me/openai")
    ) is True


def test_apify_social_scraper_builds_keyword_and_hashtag_inputs(monkeypatch):
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            captured.append(json.loads(request.content))
            return httpx.Response(200, json=_run_resp(f"run{len(captured)}", f"ds{len(captured)}"))
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json=_status_resp())
        if "/datasets/" in request.url.path:
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.url}")

    config = _social_config(
        _sub("x", "keyword", "Claude Code MCP"),
        _sub("instagram", "hashtag", "#aiagents"),
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    asyncio.run(ApifySocialScraper(config, client).fetch(datetime.now(timezone.utc) - timedelta(hours=1)))
    asyncio.run(client.aclose())

    assert captured[0] == {"searchTerms": ["Claude Code MCP"], "maxItems": 3}
    assert captured[1]["directUrls"] == ["https://www.instagram.com/explore/tags/aiagents/"]


def test_apify_social_scraper_skips_when_token_missing(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    items = asyncio.run(
        ApifySocialScraper(
            _social_config(_sub("x", "profile", "OpenAI")),
            client,
        ).fetch(datetime.now(timezone.utc) - timedelta(hours=1))
    )
    asyncio.run(client.aclose())

    assert items == []


def test_apify_social_strict_mode_reports_missing_token(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    scraper = ApifySocialScraper(
        _social_config(_sub("x", "profile", "OpenAI")),
        client,
    )
    scraper.strict_errors = True

    with pytest.raises(RuntimeError, match="APIFY_TOKEN") as exc_info:
        asyncio.run(scraper.fetch(datetime.now(timezone.utc) - timedelta(hours=1)))
    asyncio.run(client.aclose())

    assert getattr(exc_info.value, "retryable", None) is False
