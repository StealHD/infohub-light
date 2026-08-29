"""Route-scoped input/output derivations for X profile item Actors."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

from ...discovery_virtual_fields import X_POST_URL_POINTER
from ...ports import ActorManifest, FetchWindow, TargetSpec
from .._manifest import build_input


_HANDLE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_POST_ID = re.compile(r"^[0-9]{1,32}$")


def build_profile_input(
    target: TargetSpec, manifest: ActorManifest, window: FetchWindow
) -> Mapping[str, object]:
    rendered = dict(build_input(target, manifest, window))
    template = _manifest(manifest).get("input")
    if (
        target.handle
        and isinstance(template, Mapping)
        and template.get("query") == {"$ref": "target.handle"}
        and template.get("mode") == "Advanced Search"
        and template.get("query_type") == "Latest"
    ):
        rendered["query"] = f"from:{target.handle}"
    return rendered


def derive_profile_rows(
    rows: Sequence[Mapping[str, object]], manifest: ActorManifest
) -> tuple[Mapping[str, object], ...]:
    output = _manifest(manifest).get("output")
    if not isinstance(output, Mapping) or _pointers(output.get("url")) != (X_POST_URL_POINTER,):
        return tuple(rows)
    id_pointers = _pointers(output.get("native_id"))
    author_pointers = _pointers(output.get("author_handle"))
    derived: list[Mapping[str, object]] = []
    for row in rows:
        clean_row = {
            key: value for key, value in row.items()
            if key != X_POST_URL_POINTER[1:]
        }
        native_id = _first_scalar(row, id_pointers)
        handle = _first_scalar(row, author_pointers).lstrip("@")
        if _POST_ID.fullmatch(native_id) and _HANDLE.fullmatch(handle):
            derived.append({**clean_row, X_POST_URL_POINTER[1:]: f"https://x.com/{handle}/status/{native_id}"})
        else:
            derived.append(clean_row)
    return tuple(derived)


def _manifest(manifest: ActorManifest) -> Mapping[str, object]:
    try:
        value = json.loads(manifest.manifest_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, Mapping) else {}


def _pointers(value: object) -> tuple[str, ...]:
    raw = value.get("pointers") if isinstance(value, Mapping) else None
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return ()
    return tuple(str(pointer) for pointer in raw if isinstance(pointer, str))


def _first_scalar(row: Mapping[str, object], pointers: Sequence[str]) -> str:
    for pointer in pointers:
        value: object = row
        for raw_part in pointer.removeprefix("/").split("/"):
            part = raw_part.replace("~1", "/").replace("~0", "~")
            value = value.get(part) if isinstance(value, Mapping) else None
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()
    return ""


__all__ = ["build_profile_input", "derive_profile_rows"]
