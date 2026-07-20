import json


def test_response_schema_keeps_paths_and_types_without_values() -> None:
    from src.services.response_schema import extract_response_schema

    secret = "sk-private-do-not-store"
    schema = extract_response_schema(
        [
            {
                "author": {
                    "profilePicture": "https://pbs.twimg.com/a.jpg?token=secret"
                },
                "count": 1,
                "ok": True,
                "secret": secret,
            },
            {
                "author": {"profilePicture": None},
                "count": 1.5,
                "ok": False,
            },
        ]
    )

    assert schema["root_type"] == "array"
    fields = {field["path"]: field["type"] for field in schema["fields"]}
    assert {key: fields[key] for key in (
        "author",
        "author.profilePicture",
        "count",
        "ok",
        "secret",
    )} == {
        "author": "object",
        "author.profilePicture": "mixed",
        "count": "mixed",
        "ok": "boolean",
        "secret": "string",
    }
    serialized = json.dumps(schema)
    assert secret not in serialized
    assert "pbs.twimg.com" not in serialized


def test_response_schema_is_deterministic_and_enforces_all_bounds() -> None:
    from src.services.response_schema import (
        bound_source_response_schemas,
        extract_response_schema,
    )

    assert extract_response_schema([]) == {
        "root_type": "array",
        "fields": [],
        "truncated": False,
    }
    assert extract_response_schema({"flag": True})["fields"] == [
        {"path": "flag", "type": "boolean"}
    ]
    assert extract_response_schema({"value used as a key\n": 1})["fields"][0][
        "path"
    ] == "[dynamic-key]"
    assert extract_response_schema({"z": 1, "a": 1})["fields"] == [
        {"path": "a", "type": "integer"},
        {"path": "z", "type": "integer"},
    ]
    nested = {"g": 1}
    for key in reversed(("a", "b", "c", "d", "e", "f")):
        nested = {key: nested}
    assert extract_response_schema(nested)["truncated"] is True

    many_fields = extract_response_schema({f"field_{index}": index for index in range(300)})
    assert many_fields["truncated"] is True
    assert len(many_fields["fields"]) <= 256
    assert len(
        json.dumps(many_fields, ensure_ascii=False, separators=(",", ":")).encode()
    ) <= 8192

    oversized_records = [
        {
            "source_id": f"source_{index}",
            "upstream": extract_response_schema(
                {f"field_{field:03d}": field for field in range(256)}
            ),
        }
        for index in range(20)
    ]
    bounded = bound_source_response_schemas(oversized_records)
    assert len(
        json.dumps(bounded, ensure_ascii=False, separators=(",", ":")).encode()
    ) <= 65536
    assert bounded[-1]["job_truncated"] is True


def test_safe_run_diagnostics_exposes_bounded_dual_response_schema() -> None:
    from src.services.feed_run import FeedRunResult, SourceOutcome, safe_run_diagnostics

    upstream = {
        "root_type": "array",
        "fields": [{"path": "author.profilePicture", "type": "string"}],
        "truncated": False,
    }
    normalized = {
        "root_type": "array",
        "fields": [{"path": "metadata.author_avatar_url", "type": "string"}],
        "truncated": False,
    }
    result = FeedRunResult(
        run_id="run_schema",
        status="succeeded",
        started_at="2026-07-16T00:00:00+00:00",
        finished_at="2026-07-16T00:00:01+00:00",
        source_outcomes=(
            SourceOutcome(
                source_id="src_x",
                subscription_id="sub_x",
                source_key="apify_social:x:profile:example",
                analysis_mode="full",
                status="succeeded",
                fetched_count=1,
                catalog_type="apify_social",
                capture_status="captured",
                upstream_schema=upstream,
                normalized_schema=normalized,
            ),
        ),
    )

    diagnostics = safe_run_diagnostics(result, item_count=1)

    assert diagnostics["response_schemas"] == [
        {
            "source_id": "src_x",
            "catalog_type": "apify_social",
            "capture_status": "captured",
            "upstream": upstream,
            "normalized": normalized,
        }
    ]


def test_base_scraper_observes_only_merged_response_structure() -> None:
    from src.scrapers.base import BaseScraper

    class ExampleScraper(BaseScraper):
        async def fetch(self, since):
            return []

    scraper = ExampleScraper({}, None)
    scraper.observe_upstream_response(
        {"author": {"name": "private-name"}, "items": [{"id": "private-id"}]}
    )
    scraper.observe_upstream_response(
        {"author": {"avatar": "https://private.example/avatar"}}
    )

    schema = scraper.upstream_response_schema
    fields = {field["path"]: field["type"] for field in schema["fields"]}
    assert fields == {
        "author": "object",
        "author.avatar": "string",
        "author.name": "string",
        "items": "array",
        "items.id": "string",
    }
    serialized = json.dumps(schema)
    assert "private-name" not in serialized
    assert "private-id" not in serialized
    assert "private.example" not in serialized
