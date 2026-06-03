from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from src.services.scheduler import _next_poll_run


def test_next_poll_run_uses_minute_interval():
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 6, 3, 10, 0, tzinfo=tz)

    assert _next_poll_run(now, 30) == datetime(2026, 6, 3, 10, 30, tzinfo=tz)


def test_next_poll_run_rejects_non_positive_interval():
    tz = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 6, 3, 10, 0, tzinfo=tz)

    with pytest.raises(ValueError, match="poll interval"):
        _next_poll_run(now, 0)
