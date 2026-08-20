from src.services.apify_actor_candidate_quality import (
    actor_store_quality,
    quality_sort_key,
    store_actor_quality,
    with_store_quality,
)
from src.services.apify_actor_discovery import DiscoveryCandidate
from src.services.apify_actor_discovery_quality import (
    discovery_minimum_requirements,
    discovery_revision_security_evidence,
    rank_discovery_candidates,
)


def test_store_quality_normalizes_public_rating_reviews_and_users() -> None:
    quality = store_actor_quality({
        "stats": {
            "actorReviewRating": 4.7,
            "actorReviewCount": 152,
            "totalUsers": 195_000,
        },
    })
    assert quality == {"rating": 4.7, "rating_count": 152, "user_count": 195_000}


def test_store_quality_reads_store_search_review_field_names() -> None:
    quality = store_actor_quality({
        "reviewRating": 4.7,
        "reviewCount": 152,
        "totalUsers": 195_000,
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
    def candidate(actor_id: str, rating: float, users: int) -> DiscoveryCandidate:
        return DiscoveryCandidate(
            actor_id=actor_id,
            publisher=actor_id.split("/")[0],
            build_id="build",
            build_number="1",
            actor={
                "stats": {
                    "actorReviewRating": rating,
                    "actorReviewCount": 152,
                    "totalUsers": users,
                },
            },
            build={},
            input_schema={},
            output_schema={},
            pricing={},
            input_template={},
        )

    ranked = rank_discovery_candidates(
        [
            candidate("publisher/less-used", 4.7, 25_000),
            candidate("publisher/established", 4.7, 195_000),
        ],
        {
            # `responseFormat=agent` search rows carry no rating fields.
            "publisher/less-used": {"actorId": "publisher/less-used"},
            "publisher/established": {"actorId": "publisher/established"},
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


def test_discovery_prefers_higher_rating_over_higher_usage() -> None:
    def candidate(actor_id: str, rating: float, users: int) -> DiscoveryCandidate:
        return DiscoveryCandidate(
            actor_id=actor_id,
            publisher=actor_id.split("/")[0],
            build_id="build",
            build_number="1",
            actor={
                "stats": {
                    "actorReviewRating": rating,
                    "actorReviewCount": 10,
                    "totalUsers": users,
                },
            },
            build={},
            input_schema={},
            output_schema={},
            pricing={},
            input_template={},
        )

    ranked = rank_discovery_candidates(
        [
            candidate("pub/high-usage-low-rating", 4.1, 500_000),
            candidate("pub/low-usage-high-rating", 4.9, 1_000),
        ],
        {},
        set(),
        lambda _schema: True,
    )
    assert [item.actor_id for item in ranked] == [
        "pub/low-usage-high-rating", "pub/high-usage-low-rating",
    ]


def test_revision_evidence_freezes_public_store_quality() -> None:
    candidate = DiscoveryCandidate(
        actor_id="publisher/established",
        publisher="publisher",
        build_id="build",
        build_number="1",
        actor={
            "isPublic": True,
            "isDeprecated": False,
            "stats": {
                "actorReviewRating": 4.7,
                "actorReviewCount": 152,
                "totalUsers": 195_000,
            },
        },
        build={},
        input_schema={},
        output_schema={},
        pricing={},
        input_template={},
    )
    enriched = with_store_quality(candidate, {"actorId": "publisher/established"})
    evidence = discovery_revision_security_evidence(
        enriched.actor,
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
