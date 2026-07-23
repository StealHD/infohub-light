from scripts.check_product_docs import (
    DOCUMENTATION_SOURCES,
    ChangedPath,
    documentation_check,
    is_product_code,
)


def _modified(path: str) -> ChangedPath:
    return ChangedPath(status="M", path=path)


def test_product_code_requires_both_manual_and_changelog_sources():
    changes = [_modified("src/api/server.py")]

    result = documentation_check(changes)

    assert result["required"] is True
    assert set(result["missing"]) == DOCUMENTATION_SOURCES


def test_reviewing_both_sources_satisfies_product_documentation_gate():
    changes = [
        _modified("frontend/src/app/App.tsx"),
        *[_modified(path) for path in sorted(DOCUMENTATION_SOURCES)],
    ]

    result = documentation_check(changes)

    assert result["required"] is True
    assert result["missing"] == []
    assert set(result["documentation_sources"]) == DOCUMENTATION_SOURCES


def test_test_and_control_only_changes_do_not_require_product_documentation():
    changes = [
        _modified("frontend/src/app/App.test.tsx"),
        _modified("tests/test_api_service.py"),
        _modified("scripts/test_gate.py"),
        _modified("WORKLOG.md"),
    ]

    result = documentation_check(changes)

    assert result["required"] is False
    assert result["missing"] == []


def test_deleted_or_renamed_product_code_still_requires_review():
    changes = [
        ChangedPath(status="D", path="src/legacy.py"),
        ChangedPath(
            status="R",
            previous_path="frontend/src/features/old.ts",
            path="frontend/src/features/new.ts",
        ),
    ]

    result = documentation_check(changes)

    assert result["required"] is True
    assert result["missing"]
    assert is_product_code("frontend/src/features/new.ts") is True


def test_documentation_source_deletion_does_not_count_as_review():
    changes = [
        _modified("src/services/worker.py"),
        ChangedPath(
            status="D",
            path="frontend/src/features/manual/manualContent.ts",
        ),
        _modified("frontend/src/features/changelog/changelogEntries.ts"),
    ]

    result = documentation_check(changes)

    assert result["missing"] == ["frontend/src/features/manual/manualContent.ts"]
