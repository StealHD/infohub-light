"""Synthetic values reproducing observed flat author / coauthor dataset shapes."""
from copy import deepcopy
import pytest

from src.services.apify_actor_manifest import ActorManifestError
from test_actorops_structured_mapping import document, row, validate


@pytest.mark.parametrize("author_field", ["author_username", "authorUsername", "unknownAuthorField"])
def test_flat_manifest_paths_share_contributor_port_and_keep_media(author_field):
    doc = document()
    doc.pop("structures")
    doc["output"]["author_handle"]["pointers"] = ["/" + author_field]
    collaboration = row("brand")
    collaboration[author_field] = collaboration.pop("k5")
    collaboration["coauthor_producers"] = [{"username": "target",
        "profile_pic_url": "https://cdn.example/target.jpg"}]
    collaboration["images"] = collaboration.pop("stuff")
    direct = {**row(), "k1": "two", "k2": "https://www.instagram.com/p/two/"}
    direct[author_field] = direct.pop("k5")
    direct["coauthor_producers"] = None
    rows = [collaboration, direct]
    original, original_doc = deepcopy(rows), deepcopy(doc)
    batch = validate(doc, rows)
    item = next(item for item in batch.items if item.metadata["native_id"] == "one")
    assert len(batch.items) == 2
    assert item.author == "brand"
    assert item.metadata["media_urls"] == original[0]["images"]
    assert item.metadata["contributors"][0]["handle"] == "target"
    assert batch.source_avatar_url == "https://cdn.example/target.jpg"
    assert rows == original and doc == original_doc


@pytest.mark.parametrize("kind", ["absent", "invited", "foreign", "overflow", "explicit"])
def test_legacy_projection_never_invents_membership_or_overrides_explicit_mapping(kind):
    doc, item = document(), row("brand")
    doc.pop("structures")
    if kind == "invited":
        item["invited_coauthor_producers"] = [{"username": "target"}]
    elif kind == "foreign":
        item["coauthor_producers"] = [{"username": "other"}]
    elif kind == "overflow":
        item["coauthor_producers"] = [{"username": "target"}] * 17
    elif kind == "explicit":
        doc["structures"] = {}
        item["coauthor_producers"] = [{"username": "target"}]
    with pytest.raises(ActorManifestError):
        validate(doc, [item])
