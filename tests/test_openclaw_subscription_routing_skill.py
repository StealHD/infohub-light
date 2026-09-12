from tests.test_openclaw_skill import all_skill_text


def test_skill_routes_from_guide_and_recovers_without_repeated_resolution():
    combined = " ".join(all_skill_text().split())

    assert "configuration_required" in combined
    assert "resolver_not_supported" in combined
    assert "do not call `resolve_source` again" in combined
    assert "use the public fields the user already supplied" in combined
    assert "ask only for missing `required_fields`" in combined
    assert "`source_requires_web_setup`" in combined
    assert "do not bypass" in combined
    assert "prepare writes a sealed proposal" in combined
    assert "apply writes the business objects" in combined


def test_skill_has_direct_github_and_hackernews_envelopes():
    flattened = "".join(all_skill_text().split())

    assert (
        '"source":{"mode":"private","type":"github",'
        '"display_name":"OpenClawReleases",'
        '"config":{"repository":"openclaw/openclaw"}}'
    ) in flattened
    assert (
        '"source":{"mode":"private","type":"hackernews",'
        '"display_name":"HackerNews","config":{}}}'
    ) in flattened
