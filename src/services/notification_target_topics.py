"""Purpose-bound Telegram topic metadata for notification targets."""

from ..storage.notification_extension_schema import ready
from .notification_telegram_transport import normalize_telegram_message_thread_id


def get_topic(store, target_id: str) -> int | None:
    conn = store.connect()
    if not ready(conn):
        return None
    row = conn.execute(
        "SELECT message_thread_id FROM notification_target_topics WHERE target_id=?",
        (target_id,),
    ).fetchone()
    return int(row[0]) if row else None


def set_topic(store, target_id: str, value) -> int | None:
    conn = store.connect()
    if not ready(conn):
        raise ValueError("notification destinations global 47 migration is required")
    topic = normalize_telegram_message_thread_id(value)
    if topic is None:
        conn.execute("DELETE FROM notification_target_topics WHERE target_id=?", (target_id,))
    else:
        conn.execute(
            "INSERT INTO notification_target_topics(target_id,message_thread_id) VALUES(?,?) "
            "ON CONFLICT(target_id) DO UPDATE SET message_thread_id=excluded.message_thread_id",
            (target_id, topic),
        )
    return topic
