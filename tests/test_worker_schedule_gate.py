"""The resident Worker can process explicit work while local schedules pause."""

from src.services.worker_schedule_gate import worker_schedule_polling_enabled


def test_worker_schedule_polling_defaults_on_and_accepts_explicit_pause(
    monkeypatch,
) -> None:
    monkeypatch.delenv("HORIZON_SCHEDULE_POLL_ENABLED", raising=False)
    assert worker_schedule_polling_enabled() is True
    monkeypatch.setenv("HORIZON_SCHEDULE_POLL_ENABLED", "false")
    assert worker_schedule_polling_enabled() is False
