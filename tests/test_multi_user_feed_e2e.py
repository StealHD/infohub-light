import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from src.services.feed_schedule import FeedScheduleService
from src.services.job_queue import JobQueue
from src.services.user_feed_store import UserFeedStore
from src.services.worker import run_worker_once
from src.storage.service_store import ServiceStore


def _feed(title: str, guid: str) -> bytes:
    published = format_datetime(datetime.now(timezone.utc), usegmt=True)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>{title}</title>
      <item><guid>{guid}</guid><title>{title}</title>
      <link>https://example.com/{guid}</link><pubDate>{published}</pubDate>
      <description>{title}</description></item>
    </channel></rss>""".encode()


def _start_feed_server(feeds: dict[str, bytes]) -> tuple[ThreadingHTTPServer, Thread]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = feeds.get(self.path)
            if body is None:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_real_worker_keeps_private_user_feeds_isolated_sequentially_and_concurrently(tmp_path, monkeypatch):
    feeds = {
        "/alice.xml": _feed("Alice private item", "alice-1"),
        "/bob.xml": _feed("Bob private item", "bob-1"),
    }

    server, thread = _start_feed_server(feeds)
    try:
        monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
        monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
        monkeypatch.setenv("HORIZON_MEMBER_RSS_HOST_ALLOWLIST", "127.0.0.1")
        (tmp_path / "config.json").write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "ai": {"enabled": False, "provider": "openai", "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY"},
                    "sources": {"rss": [], "github": [], "hackernews": {"enabled": False}},
                    "filtering": {"time_window_hours": 24},
                }
            ),
            encoding="utf-8",
        )
        store = ServiceStore(tmp_path)
        store.initialize()
        workspace = store.get_default_workspace()
        alice = store.get_user_by_username("owner")
        bob = store.create_user(
            workspace_id=workspace["id"], username="bob", password="bob-password", role="member"
        )
        alice_source = store.create_source(
            workspace_id=workspace["id"],
            scope="private",
            owner_user_id=alice["id"],
            source_type="rss",
            display_name="Alice RSS",
            config={"name": "Alice RSS", "url": f"http://127.0.0.1:{server.server_port}/alice.xml"},
            source_key=f"rss:http://127.0.0.1:{server.server_port}/alice.xml",
        )
        bob_source = store.create_source(
            workspace_id=workspace["id"],
            scope="private",
            owner_user_id=bob["id"],
            source_type="rss",
            display_name="Bob RSS",
            config={"name": "Bob RSS", "url": f"http://127.0.0.1:{server.server_port}/bob.xml"},
            source_key=f"rss:http://127.0.0.1:{server.server_port}/bob.xml",
        )
        store.create_subscription(user_id=alice["id"], source_id=alice_source)
        store.create_subscription(user_id=bob["id"], source_id=bob_source)
        queue = JobQueue(store)
        for user in (alice, bob):
            queue.create_job(
                workspace_id=workspace["id"], user_id=user["id"], job_type="user_feed_refresh"
            )

        first = run_worker_once(data_dir=str(tmp_path), worker_id="worker-a")
        second = run_worker_once(data_dir=str(tmp_path), worker_id="worker-b")

        assert {first["status"], second["status"]} == {"succeeded"}
        feed_store = UserFeedStore(store)
        alice_feed = feed_store.latest_snapshot(workspace_id=workspace["id"], user_id=alice["id"])
        bob_feed = feed_store.latest_snapshot(workspace_id=workspace["id"], user_id=bob["id"])
        assert [item["title"] for item in alice_feed["payload"]["items"]] == ["Alice private item"]
        assert [item["title"] for item in bob_feed["payload"]["items"]] == ["Bob private item"]
        assert not (tmp_path / "site" / "radar-data.json").exists()

        for user in (alice, bob):
            queue.create_job(
                workspace_id=workspace["id"], user_id=user["id"], job_type="user_feed_refresh"
            )
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda worker: run_worker_once(data_dir=str(tmp_path), worker_id=worker),
                    ("worker-c", "worker-d"),
                )
            )

        assert [result["status"] for result in results] == ["succeeded", "succeeded"]
        alice_ids = {
            item["id"]
            for item in feed_store.latest_snapshot(workspace_id=workspace["id"], user_id=alice["id"])["payload"]["items"]
        }
        bob_ids = {
            item["id"]
            for item in feed_store.latest_snapshot(workspace_id=workspace["id"], user_id=bob["id"])["payload"]["items"]
        }
        assert alice_ids
        assert bob_ids
        assert alice_ids.isdisjoint(bob_ids)

        deterministic_results = []
        for batch in range(10):
            for user in (alice, bob):
                queue.create_job(
                    workspace_id=workspace["id"],
                    user_id=user["id"],
                    job_type="user_feed_refresh",
                )
            with ThreadPoolExecutor(max_workers=2) as executor:
                deterministic_results.extend(
                    executor.map(
                        lambda worker: run_worker_once(
                            data_dir=str(tmp_path),
                            worker_id=worker,
                        ),
                        (f"canary-{batch}-a", f"canary-{batch}-b"),
                    )
                )

        assert len(deterministic_results) == 20
        assert {result["status"] for result in deterministic_results} == {"succeeded"}
        duplicate_snapshots = store.connect().execute(
            """
            SELECT job_id, COUNT(*) AS count
            FROM user_feed_snapshots
            WHERE job_id IS NOT NULL
            GROUP BY job_id
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        assert duplicate_snapshots == []
        assert store.connect().execute("PRAGMA foreign_key_check").fetchall() == []
        alice_ids = {
            item["id"]
            for item in feed_store.latest_snapshot(
                workspace_id=workspace["id"], user_id=alice["id"]
            )["payload"]["items"]
        }
        bob_ids = {
            item["id"]
            for item in feed_store.latest_snapshot(
                workspace_id=workspace["id"], user_id=bob["id"]
            )["payload"]["items"]
        }
        assert alice_ids.isdisjoint(bob_ids)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_scheduled_refresh_keeps_two_users_isolated_across_two_cycles(
    tmp_path, monkeypatch
):
    feeds = {
        "/alice.xml": _feed("Alice scheduled item", "alice-scheduled-1"),
        "/bob.xml": _feed("Bob scheduled item", "bob-scheduled-1"),
    }
    server, thread = _start_feed_server(feeds)
    store = None
    try:
        monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
        monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
        monkeypatch.setenv("HORIZON_MEMBER_RSS_HOST_ALLOWLIST", "127.0.0.1")
        (tmp_path / "config.json").write_text(
            json.dumps(
                {
                    "version": "1.0",
                    "ai": {
                        "enabled": False,
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "api_key_env": "OPENAI_API_KEY",
                    },
                    "sources": {
                        "rss": [],
                        "github": [],
                        "hackernews": {"enabled": False},
                    },
                    "filtering": {"time_window_hours": 24},
                }
            ),
            encoding="utf-8",
        )
        store = ServiceStore(tmp_path)
        store.initialize()
        workspace = store.get_default_workspace()
        alice = store.get_user_by_username("owner")
        bob = store.create_user(
            workspace_id=workspace["id"],
            username="bob",
            password="bob-password",
            role="member",
        )
        for user, slug, display_name in (
            (alice, "alice", "Alice scheduled RSS"),
            (bob, "bob", "Bob scheduled RSS"),
        ):
            source_id = store.create_source(
                workspace_id=workspace["id"],
                scope="private",
                owner_user_id=user["id"],
                source_type="rss",
                display_name=display_name,
                config={
                    "name": display_name,
                    "url": f"http://127.0.0.1:{server.server_port}/{slug}.xml",
                },
                source_key=f"rss:http://127.0.0.1:{server.server_port}/{slug}.xml",
            )
            store.create_subscription(user_id=user["id"], source_id=source_id)

        schedules = FeedScheduleService(store)
        feed_store = UserFeedStore(store)
        cycle_one_at = datetime(2026, 7, 11, 0, 0, tzinfo=timezone.utc)
        for user in (alice, bob):
            schedules.update_user_schedule(
                workspace_id=workspace["id"],
                user_id=user["id"],
                enabled=True,
                interval_minutes=60,
                now=cycle_one_at,
            )

        def scheduled_jobs():
            rows = store.connect().execute(
                """
                SELECT * FROM fetch_jobs
                WHERE job_type = 'user_feed_refresh'
                  AND json_extract(payload_json, '$.reason') = 'scheduled_service_refresh'
                ORDER BY created_at, id
                """
            ).fetchall()
            return [store._job(row) for row in rows]

        def snapshot_counts():
            return {
                row["user_id"]: row["count"]
                for row in store.connect().execute(
                    """
                    SELECT user_id, COUNT(*) AS count
                    FROM user_feed_snapshots
                    GROUP BY user_id
                    """
                ).fetchall()
            }

        def latest_ids(user):
            snapshot = feed_store.latest_snapshot(
                workspace_id=workspace["id"],
                user_id=user["id"],
            )
            assert snapshot is not None
            return {item["id"] for item in snapshot["payload"]["items"]}

        def run_workers(cycle: int):
            with ThreadPoolExecutor(max_workers=2) as executor:
                return list(
                    executor.map(
                        lambda worker_id: run_worker_once(
                            data_dir=str(tmp_path),
                            worker_id=worker_id,
                            enqueue_schedules=False,
                        ),
                        (f"scheduled-{cycle}-a", f"scheduled-{cycle}-b"),
                    )
                )

        first_enqueue = schedules.enqueue_due(now=cycle_one_at)
        first_jobs = scheduled_jobs()
        assert first_enqueue["evaluated"] == 2
        assert first_enqueue["enqueued"] == 2
        assert len(first_jobs) == 2
        assert {job["user_id"] for job in first_jobs} == {alice["id"], bob["id"]}
        assert all(
            job["payload_json"] == {"reason": "scheduled_service_refresh"}
            for job in first_jobs
        )
        assert all(job["priority"] == -10 for job in first_jobs)
        assert schedules.enqueue_due(now=cycle_one_at)["evaluated"] == 0
        assert len(scheduled_jobs()) == 2

        first_results = run_workers(1)
        assert len(first_results) == 2
        assert all(
            result is not None and result["status"] in {"succeeded", "partial"}
            for result in first_results
        )
        assert snapshot_counts() == {alice["id"]: 1, bob["id"]: 1}
        alice_ids = latest_ids(alice)
        bob_ids = latest_ids(bob)
        assert alice_ids
        assert bob_ids
        assert alice_ids.isdisjoint(bob_ids)

        cycle_two_at = cycle_one_at + timedelta(minutes=60)
        second_enqueue = schedules.enqueue_due(now=cycle_two_at)
        all_jobs = scheduled_jobs()
        assert second_enqueue["evaluated"] == 2
        assert second_enqueue["enqueued"] == 2
        assert len(all_jobs) == 4
        assert len({job["id"] for job in all_jobs}) == 4
        assert all(
            job["payload_json"] == {"reason": "scheduled_service_refresh"}
            for job in all_jobs
        )
        first_job_ids = {job["id"] for job in first_jobs}
        second_jobs_by_user = {
            job["user_id"]: job["id"]
            for job in all_jobs
            if job["id"] not in first_job_ids
        }
        assert set(second_jobs_by_user) == {alice["id"], bob["id"]}
        assert schedules.enqueue_due(now=cycle_two_at)["evaluated"] == 0
        assert len(scheduled_jobs()) == 4

        second_results = run_workers(2)
        assert len(second_results) == 2
        assert all(
            result is not None and result["status"] in {"succeeded", "partial"}
            for result in second_results
        )
        assert snapshot_counts() == {alice["id"]: 1, bob["id"]: 1}
        assert all(
            result["result_json"]["snapshot_created"] is False
            for result in second_results
        )
        alice_ids = latest_ids(alice)
        bob_ids = latest_ids(bob)
        assert alice_ids
        assert bob_ids
        assert alice_ids.isdisjoint(bob_ids)

        snapshots_per_job = {
            row["job_id"]: row["count"]
            for row in store.connect().execute(
                """
                SELECT job_id, COUNT(*) AS count
                FROM user_feed_snapshots
                WHERE job_id IS NOT NULL
                GROUP BY job_id
                """
            ).fetchall()
        }
        assert set(snapshots_per_job) == first_job_ids
        assert all(count == 1 for count in snapshots_per_job.values())
        assert all(
            job["status"] in {"succeeded", "partial"}
            for job in scheduled_jobs()
        )

        expected_next_run = (cycle_two_at + timedelta(minutes=60)).isoformat()
        for user in (alice, bob):
            schedule = schedules.get_user_schedule(
                workspace_id=workspace["id"],
                user_id=user["id"],
            )
            assert schedule["enabled"] is True
            assert schedule["interval_minutes"] == 60
            assert schedule["next_run_at"] == expected_next_run
            assert schedule["last_evaluated_at"] == cycle_two_at.isoformat()
            assert schedule["last_enqueued_at"] == cycle_two_at.isoformat()
            assert schedule["last_job_id"] == second_jobs_by_user[user["id"]]
            assert schedule["last_skip_reason"] is None

        assert store.connect().execute("PRAGMA foreign_key_check").fetchall() == []
        for legacy_path in ("site", "radar", "history", "graph"):
            assert not (tmp_path / legacy_path).exists()
    finally:
        if store is not None:
            store.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
