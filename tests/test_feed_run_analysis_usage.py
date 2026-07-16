from src.services.feed_run import AnalysisUsage, FeedRunResult, safe_run_diagnostics


def test_safe_run_diagnostics_exposes_bounded_analysis_usage() -> None:
    result = FeedRunResult(
        run_id="run_usage",
        status="succeeded",
        started_at="2026-07-14T00:00:00+00:00",
        finished_at="2026-07-14T00:00:01+00:00",
        analysis_usage=AnalysisUsage(
            item_count=8,
            cache_hits=5,
            ai_calls=2,
            provider_attempts=3,
            fallbacks=1,
            skipped=1,
        ),
    )

    diagnostics = safe_run_diagnostics(result, item_count=8)

    assert diagnostics["analysis_usage"] == {
        "item_count": 8,
        "cache_hits": 5,
        "ai_calls": 2,
        "provider_attempts": 3,
        "fallbacks": 1,
        "skipped": 1,
    }
