"""Deterministic trigger clocks; calendar gaps skip and folds run only once."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def next_due(trigger, after):
    if trigger.kind == 'interval':
        return after + timedelta(seconds=trigger.interval_seconds)
    if trigger.kind != 'calendar':
        return None
    local = after.astimezone(ZoneInfo(trigger.timezone))
    hour, minute = map(int, trigger.time.split(':'))
    for offset in range(16):
        day = local.date() + timedelta(days=offset)
        if trigger.weekdays and day.weekday() not in trigger.weekdays:
            continue
        candidate = datetime.combine(day, datetime.min.time(), local.tzinfo).replace(hour=hour, minute=minute, fold=0)
        utc = candidate.astimezone(timezone.utc)
        if utc.astimezone(local.tzinfo).replace(tzinfo=None) != candidate.replace(tzinfo=None):
            continue
        if utc > after:
            return utc
    raise ValueError('No valid calendar occurrence')


def due_count(trigger, events, scheduled_at, now):
    if not events:
        return 0
    if trigger.kind == 'each':
        return 1
    if trigger.kind == 'count':
        if len(events) >= trigger.count:
            return trigger.count
        if trigger.max_wait_seconds is not None and now >= datetime.fromisoformat(events[0]['created_at']) + timedelta(seconds=trigger.max_wait_seconds):
            return len(events)
        return 0
    return len(events) if scheduled_at and datetime.fromisoformat(scheduled_at) <= now else 0


def advance_due(trigger, scheduled, now):
    if trigger.kind == 'interval':
        previous = datetime.fromisoformat(scheduled)
        elapsed = (now - previous).total_seconds()
        return previous + timedelta(seconds=(int(elapsed // trigger.interval_seconds) + 1) * trigger.interval_seconds)
    return next_due(trigger, now)


def batch_cutoff(trigger, scheduled, now):
    """Use the last elapsed boundary; combine missed cycles without taking future work."""
    if not scheduled or trigger.kind not in {'interval', 'calendar'}:
        return now
    previous = datetime.fromisoformat(scheduled)
    if previous > now:
        return previous
    if trigger.kind == 'interval':
        return advance_due(trigger, scheduled, now) - timedelta(seconds=trigger.interval_seconds)
    candidate = next_due(trigger, now - timedelta(days=16))
    while candidate <= now:
        previous = max(previous, candidate)
        candidate = next_due(trigger, candidate)
    return previous
