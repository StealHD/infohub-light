from src.services.apify_actor_candidate_quality import (
    actor_store_quality,
    quality_sort_key,
    store_actor_quality,
)
from src.services.apify_actor_discovery import DiscoveryCandidate
from src.services.apify_actor_discovery_quality import (
    discovery_minimum_requirements,
    discovery_revision_security_evidence,
    rank_discovery_candidates,
)


def test_store_quality_normalizes_public_rating_reviews_and_users() -> None:
    quality = store_actor_quality({
        "rating": 4.7,
        "ratingCount": 152,
        "stats": {"totalUsers": 195_000},
    })
    assert quality == {"rating": 4.7, "rating_count": 152, "user_count": 195_000}


def test_quality_sort_prefers_rating_then_rating_count_then_users() -> None:
    rows = [
        ("publisher/one", {"rating": 4.7, "rating_count": 152, "user_count": 195_000}),
        ("publisher/two", {"rating": 4.7, "rating_count": 152, "user_count": 25_000}),
        ("publisher/three", {"rating": 4.6, "rating_count": 1_000, "user_count": 500_000}),
    ]
    assert [actor_id for actor_id, _quality in sorted(
        rows,
        key=lambda item: quality_sort_key(item[0], item[1], preferred=False),
    )] == ["publisher/one", "publisher/two", "publisher/three"]


def test_discovery_enriches_and_ranks_only_already_safe_candidates() -> None:
    candidate = lambda actor_id: DiscoveryCandidate(
        actor_id=actor_id, publisher=actor_id.split("/")[0], build_id="build",
        build_number="1", actor={}, build={}, input_schema={}, output_schema={},
        pricing={}, input_template={},
    )
    ranked = rank_discovery_candidates(
        [candidate("publisher/less-used"), candidate("publisher/established")],
        {
            "publisher/less-used": {"rating": 4.7, "ratingCount": 152, "totalUsers": 25_000},
            "publisher/established": {"rating": 4.7, "ratingCount": 152, "totalUsers": 195_000},
        },
        set(),
        lambda _schema: True,
    )
    assert [item.actor_id for item in ranked] == [
        "publisher/established", "publisher/less-used",
    ]
    assert actor_store_quality(ranked[0].actor) == {
        "rating": 4.7, "rating_count": 152, "user_count": 195_000,
    }


def test_revision_evidence_freezes_public_store_quality() -> None:
    evidence = discovery_revision_security_evidence(
        {"isPublic": True, "isDeprecated": False, "rating": 4.7, "ratingCount": 152, "totalUsers": 195_000},
        output_schema_proves_items=True,
    )
    assert evidence["store_quality"] == {
        "rating": 4.7, "rating_count": 152, "user_count": 195_000,
    }


def test_slot_refresh_requires_one_safe_candidate_without_weakening_pool_discovery() -> None:
    route = {"min_runtime_healthy": 2, "min_publishers": 2}
    assert discovery_minimum_requirements(
        {"trigger_reason": "manual_slot_candidate_refresh"}, route
    ) == (1, 1)
    assert discovery_minimum_requirements(
        {"trigger_reason": "manual_candidate_refresh"}, route
    ) == (2, 2)
