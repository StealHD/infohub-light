from src.ai.tokens import get_usage_snapshot, record_usage, reset_usage, token_stage


def test_token_usage_tracks_stage_totals():
    reset_usage()

    with token_stage("analysis", item_id="rss:test:1"):
        record_usage("openai", input_tokens=10, output_tokens=5)
    with token_stage("summary"):
        record_usage("openai", input_tokens=7, output_tokens=3)

    snapshot = get_usage_snapshot()

    assert snapshot.total_tokens == 25
    assert snapshot.per_provider["openai"].total == 25
    assert snapshot.per_stage["analysis"].total == 15
    assert snapshot.per_stage["summary"].input_tokens == 7
