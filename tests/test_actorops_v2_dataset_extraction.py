from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.services.actorops.observed_dataset_schema import observed_dataset_schema
from src.services.apify_actor_row_extraction import (
    DatasetExtractionError,
    RowExtractionPlan,
    RowFilter,
    extract_dataset_rows,
    projected_output_schema,
)


def test_flat_dataset_remains_unchanged() -> None:
    rows = ({"id": "one", "createdAt": "2030-01-01T00:00:00Z"},)

    extracted = extract_dataset_rows(rows, None)

    assert extracted.rows == rows
    assert extracted.shape == "flat"


def test_nested_dataset_projects_item_parent_and_root() -> None:
    rows = ({
        "channel": {"handle": "@safe"},
        "data": {
            "kind": "timeline",
            "items": [{"id": "one", "title": "new", "publishedAt": "2030-01-01"}],
        },
    },)
    plan = RowExtractionPlan(mode="nested_array", pointers=("/data/items",))

    extracted = extract_dataset_rows(rows, plan)

    assert extracted.shape == "nested"
    assert extracted.rows == ({
        "item": {"id": "one", "title": "new", "publishedAt": "2030-01-01"},
        "parent": {
            "kind": "timeline",
            "items": [{"id": "one", "title": "new", "publishedAt": "2030-01-01"}],
        },
        "root": rows[0],
    },)


def test_nested_pointer_supports_two_array_wildcard_layers() -> None:
    rows = ({
        "timeline": [{"instructions": [{"entries": [{"id": "one"}]}]}],
    },)
    plan = RowExtractionPlan(
        mode="nested_array",
        pointers=("/timeline/*/instructions/*/entries",),
    )

    extracted = extract_dataset_rows(rows, plan)

    assert extracted.rows[0]["item"] == {"id": "one"}
    assert extracted.rows[0]["parent"] == {"entries": [{"id": "one"}]}


def test_filter_rejects_skipped_publication_rows_fail_closed() -> None:
    rows = ({
        "records": [
            {"kind": "profile", "name": "safe"},
            {
                "kind": "tweet",
                "id": "one",
                "createdAt": "2030-01-01T00:00:00Z",
                "text": "content",
            },
        ],
    },)
    plan = RowExtractionPlan(
        mode="nested_array",
        pointers=("/records",),
        filters=(RowFilter(pointer="/item/kind", allowed_values=("profile",)),),
    )

    with pytest.raises(DatasetExtractionError) as captured:
        extract_dataset_rows(rows, plan)

    assert captured.value.code == "apify_actor_mixed_rows_unclassified"


def test_extraction_fails_closed_on_overflow_and_bad_pointer() -> None:
    plan = RowExtractionPlan(mode="nested_array", pointers=("/items",))

    with pytest.raises(DatasetExtractionError) as captured:
        extract_dataset_rows(({"items": [{"id": index} for index in range(101)]},), plan)
    assert captured.value.code == "apify_actor_dataset_expansion_overflow"

    with pytest.raises(ValidationError):
        RowExtractionPlan(
            mode="nested_array",
            pointers=("/one/*/two/*/three/*/items",),
        )
    with pytest.raises(ValidationError):
        RowExtractionPlan(mode="nested_array", pointers=("/../../items",))


def test_projected_schema_exposes_envelope_without_values() -> None:
    schema = {
        "type": "object",
        "properties": {
            "channel": {"type": "object", "properties": {"handle": {"type": "string"}}},
            "items": {
                "type": "array",
                "items": {"type": "object", "properties": {"id": {"type": "string"}}},
            },
        },
    }

    projected = projected_output_schema(
        schema, RowExtractionPlan(mode="nested_array", pointers=("/items",))
    )

    assert projected["properties"]["item"]["properties"]["id"] == {"type": "string"}
    assert projected["properties"]["root"] == schema


def test_observed_schema_redacts_content_targets_and_urls() -> None:
    schema = observed_dataset_schema(({
        "kind": "tweet",
        "text": "private body",
        "url": "https://x.com/private/status/1",
        "author": {"handle": "private-account"},
        "createdAt": "2030-01-01T00:00:00Z",
    },))
    encoded = str(schema)

    assert "private body" not in encoded
    assert "private-account" not in encoded
    assert "https://x.com/private/status/1" not in encoded
    assert schema["properties"]["kind"]["enum"] == ["tweet"]
    assert schema["properties"]["url"]["formatCategory"] == "url"
