"""System-derived output pointers allowed by exact route semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


X_POST_URL_POINTER = "/__actorops_x_post_url"
YOUTUBE_TARGET_NATIVE_ID_POINTER = "/__actorops_target_native_id"
YOUTUBE_TARGET_URL_POINTER = "/__actorops_target_url"


def virtual_output_pointer_allowed(
    manifest: Mapping[str, object], canonical: str, pointer: str
) -> bool:
    semantics = manifest.get("semantics")
    identity = semantics.get("identity") if isinstance(semantics, Mapping) else None
    hosts = semantics.get("url_host_allowlist") if isinstance(semantics, Mapping) else None
    output = manifest.get("output")
    if canonical == "source_url" and pointer == YOUTUBE_TARGET_URL_POINTER:
        return (
            isinstance(identity, Mapping)
            and identity.get("output_field") == "source_url"
            and identity.get("target_ref") == "target.canonical_url"
            and identity.get("match") == "url"
            and isinstance(hosts, Sequence)
            and not isinstance(hosts, (str, bytes, bytearray))
            and tuple(hosts) == ("youtube.com",)
            and isinstance(output, Mapping)
            and isinstance(output.get("source_url"), Mapping)
        )
    if (
        canonical == "source_native_id"
        and pointer == YOUTUBE_TARGET_NATIVE_ID_POINTER
    ):
        return (
            isinstance(identity, Mapping)
            and identity.get("output_field") == "source_native_id"
            and identity.get("target_ref") == "target.native_id"
            and identity.get("match") == "exact"
            and isinstance(hosts, Sequence)
            and not isinstance(hosts, (str, bytes, bytearray))
            and tuple(hosts) == ("youtube.com",)
            and isinstance(output, Mapping)
            and isinstance(output.get("native_id"), Mapping)
        )
    if canonical != "url" or pointer != X_POST_URL_POINTER:
        return False
    return (
        isinstance(identity, Mapping)
        and identity.get("output_field") == "author_handle"
        and identity.get("target_ref") == "target.handle"
        and identity.get("match") == "handle"
        and isinstance(hosts, Sequence)
        and not isinstance(hosts, (str, bytes, bytearray))
        and tuple(hosts) == ("x.com",)
        and isinstance(output, Mapping)
        and isinstance(output.get("native_id"), Mapping)
        and isinstance(output.get("author_handle"), Mapping)
    )


__all__ = [
    "X_POST_URL_POINTER",
    "YOUTUBE_TARGET_NATIVE_ID_POINTER",
    "YOUTUBE_TARGET_URL_POINTER",
    "virtual_output_pointer_allowed",
]
