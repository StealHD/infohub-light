from __future__ import annotations

from tests.remote_mcp_subscription_http_test_support import *  # noqa: F403

@pytest.mark.anyio
async def test_tool_schemas_forbid_extra_identity_and_keep_config_as_only_open_container(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch, writes_enabled=True)
    _user, _connection, token = _delegation(app)

    async with _mcp_session(app, token) as session:
        listed = await session.list_tools()
        tool = next(
            item for item in listed.tools if item.name == "prepare_create_subscription"
        )
        rejected_identity = await session.call_tool(
            "prepare_create_subscription",
            {
                "source": {
                    "mode": "private",
                    "type": "rss",
                    "display_name": "Forged",
                    "config": {"url": "https://example.com/forged.xml"},
                },
                "user_id": "forged-user",
            },
        )
        rejected_config = await session.call_tool(
            "prepare_create_subscription",
            {
                "source": {
                    "mode": "private",
                    "type": "rss",
                    "display_name": "Unsafe",
                    "config": {
                        "url": "https://example.com/unsafe.xml",
                        "headers": {"Authorization": "redacted-test-value"},
                    },
                }
            },
        )
        other_unsafe_configs = []
        for field, value in (
            ("secret", "never-log-this-secret"),
            ("path", "/private/unsafe-path"),
            ("sql", "SELECT private_data"),
            ("user_id", "forged-config-user"),
        ):
            other_unsafe_configs.append(
                await session.call_tool(
                    "prepare_create_subscription",
                    {
                        "source": {
                            "mode": "private",
                            "type": "rss",
                            "display_name": "Unsafe",
                            "config": {
                                "url": "https://example.com/unsafe.xml",
                                field: value,
                            },
                        }
                    },
                )
            )

    schema = tool.inputSchema
    assert schema["additionalProperties"] is False
    private_source = schema["$defs"]["PrivateSourceInput"]
    source_union = schema["properties"]["source"]
    assert source_union["discriminator"]["propertyName"] == "mode"
    assert set(source_union["discriminator"]["mapping"]) == {
        "existing",
        "resolved",
        "private",
    }
    assert "enum" not in private_source["properties"]["type"]
    assert private_source["additionalProperties"] is False
    assert set(private_source["properties"]) == {
        "mode",
        "type",
        "display_name",
        "config",
        "description",
        "default_channel",
        "default_topics",
    }
    assert private_source["properties"]["config"]["additionalProperties"] is True
    assert rejected_identity.isError is True
    assert "forged-user" not in rejected_identity.content[0].text
    assert rejected_config.isError is True
    assert rejected_config.content[0].text.endswith(": invalid_source_config")
    assert "redacted-test-value" not in rejected_config.content[0].text
    assert all(result.isError is True for result in other_unsafe_configs)
    assert all(
        result.content[0].text.endswith(": invalid_source_config")
        for result in other_unsafe_configs
    )
    serialized_errors = repr(other_unsafe_configs)
    for forbidden_value in (
        "never-log-this-secret",
        "/private/unsafe-path",
        "SELECT private_data",
        "forged-config-user",
    ):
        assert forbidden_value not in serialized_errors
    assert _table_count(app, "agent_change_proposals") == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("arguments", "sensitive_value", "expected_message"),
    [
        (
            {
                "source": {
                    "mode": "private",
                    "type": "rss",
                    "display_name": "Outer Extra",
                    "config": {"url": "https://example.com/outer.xml"},
                },
                "user_id": "outer-extra-sensitive-value",
            },
            "outer-extra-sensitive-value",
            "invalid_request",
        ),
        (
            {
                "source": {
                    "mode": "private",
                    "type": "rss",
                    "display_name": "Nested Extra",
                    "config": {"url": "https://example.com/nested.xml"},
                },
                "subscription": {"user_id": "nested-extra-sensitive-value"},
            },
            "nested-extra-sensitive-value",
            "invalid_request",
        ),
        (
            {
                "source": {
                    "type": "reddit",
                    "subreddit": "missing-mode-sensitive-value",
                }
            },
            "missing-mode-sensitive-value",
            (
                "invalid_request: source must use either "
                "{mode: existing, source_id}, "
                "{mode: resolved, resolution_ref}, or "
                "{mode: private, type, display_name, config}"
            ),
        ),
        (
            {
                "source": {
                    "mode": "invalid-discriminator-sensitive-value",
                    "source_id": "source_unused",
                }
            },
            "invalid-discriminator-sensitive-value",
            (
                "invalid_request: source must use either "
                "{mode: existing, source_id}, "
                "{mode: resolved, resolution_ref}, or "
                "{mode: private, type, display_name, config}"
            ),
        ),
        (
            {
                "source": {
                    "mode": "private",
                    "type": "rss",
                    "display_name": "Range Error",
                    "config": {"url": "https://example.com/range.xml"},
                },
                "subscription": {"priority": 987654321},
            },
            "987654321",
            "invalid_request",
        ),
    ],
    ids=("outer-extra", "nested-extra", "missing-discriminator", "discriminator", "range"),
)
async def test_authenticated_validation_failures_are_stable_audited_and_redacted(
    tmp_path, monkeypatch, caplog, arguments, sensitive_value, expected_message
):
    app = _app(tmp_path, monkeypatch, writes_enabled=True)
    _user, connection, token = _delegation(app)
    caplog.set_level(logging.INFO, logger="src.mcp.remote_server")

    async with _mcp_session(app, token) as session:
        result = await session.call_tool(
            "prepare_create_subscription",
            arguments,
        )

    assert result.isError is True
    assert result.content[0].text == expected_message
    audit_records = [
        record.getMessage()
        for record in caplog.records
        if record.name == "src.mcp.remote_server"
        and record.getMessage().startswith("remote_mcp_call ")
    ]
    assert len(audit_records) == 1
    assert re.fullmatch(
        rf"remote_mcp_call delegation_id={re.escape(connection['id'])} "
        r"tool=prepare_create_subscription proposal_id=- action=- "
        r"outcome=invalid_request elapsed_ms=\d+ request_id=mcp_[0-9a-f]{32}",
        audit_records[0],
    )
    serialized_evidence = result.content[0].text + "\n" + caplog.text
    assert sensitive_value not in serialized_evidence
    for forbidden_detail in (
        "validation error",
        "extra_forbidden",
        "union_tag_invalid",
        "less_than_equal",
        "input_value",
    ):
        assert forbidden_detail not in serialized_evidence.lower()
    assert _table_count(app, "agent_change_proposals") == 0


@pytest.mark.anyio
@pytest.mark.parametrize("exception_type", [RuntimeError, ValueError])
async def test_new_tool_internal_error_and_fixed_audit_log_are_redacted(
    tmp_path, monkeypatch, caplog, exception_type
):
    def fail_safely(*_args, **_kwargs):
        raise exception_type("Bearer hidden-diagnostic-value")

    monkeypatch.setattr(
        "src.mcp.remote_diagnostics.RemoteMCPDiagnostics.diagnose_job",
        fail_safely,
    )
    app = _app(tmp_path, monkeypatch, writes_enabled=True)
    _user, connection, token = _delegation(app)
    caplog.set_level(logging.INFO, logger="src.mcp.remote_server")

    async with _mcp_session(app, token) as session:
        result = await session.call_tool("diagnose_job", {"job_id": "job_missing"})

    assert result.isError is True
    assert "internal_error request_id=mcp_" in result.content[0].text
    assert "hidden-diagnostic-value" not in result.content[0].text
    records = [
        record.getMessage()
        for record in caplog.records
        if record.name == "src.mcp.remote_server"
        and record.getMessage().startswith("remote_mcp_call ")
    ]
    assert len(records) == 1
    assert records[0].startswith(
        f"remote_mcp_call delegation_id={connection['id']} tool=diagnose_job "
        "proposal_id=- action=- outcome=internal_error elapsed_ms="
    )
    assert " request_id=mcp_" in records[0]
    assert "job_missing" not in records[0]
    assert "hidden-diagnostic-value" not in caplog.text
