"""Restricted declarative manifests for third-party Apify Actor adapters.

The manifest language is intentionally small.  It can construct JSON input
from six runtime references and can map Dataset rows with RFC 6901 pointers and
an allowlist of deterministic transforms.  It cannot execute code, interpolate
templates, add credentials, or make its own network requests.
"""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Literal, Mapping, Sequence
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from dateutil.parser import isoparse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


MANIFEST_VERSION = 1
MAX_MANIFEST_BYTES = 64 * 1024
MAX_INPUT_DEPTH = 12
MAX_INPUT_NODES = 512
MAX_INPUT_STRING_CHARS = 2_048
MAX_OUTPUT_POINTERS = 128
MAX_POINTER_CHARS = 512
MAX_DATASET_ROWS = 100

ALLOWED_REFERENCES = frozenset(
    {
        "target.canonical_url",
        "target.native_id",
        "target.handle",
        "runtime.max_items",
        "runtime.since_iso",
        "runtime.until_iso",
    }
)
ALLOWED_TRANSFORMS = frozenset(
    {
        "pick_first",
        "to_string",
        "to_integer",
        "to_number",
        "to_boolean",
        "parse_datetime",
        "normalize_url",
        "strip_html",
    }
)

_ACTOR_ID_RE = re.compile(
    r"^(?:"
    r"[A-Za-z0-9]{8,64}"
    r"|"
    r"(?:[A-Za-z0-9][A-Za-z0-9._-]{0,62})"
    r"(?:[/~][A-Za-z0-9][A-Za-z0-9._-]{0,62})"
    r")$"
)
_BUILD_NUMBER_RE = re.compile(
    r"^(?:[0-9]|[1-9][0-9])\.(?:[0-9]|[1-9][0-9])"
    r"(?:\.(?:0|[1-9][0-9]{0,4}))$"
)
_POINTER_ESCAPE_RE = re.compile(r"~(?![01])")
_TEMPLATE_MARKERS = ("${", "{{", "}}", "<%", "%>", "javascript:")
_FORBIDDEN_INPUT_KEY_PARTS = frozenset(
    {
        "authorization",
        "auth",
        "code",
        "credential",
        "cookie",
        "header",
        "password",
        "proxy",
        "secret",
        "token",
        "apikey",
        "api_key",
        "webhook",
        "requestoptions",
        "request_options",
        "request",
        "customrequest",
        "custom_request",
        "javascript",
        "python",
        "eval",
        "function",
        "script",
        "command",
        "shell",
        "network",
    }
)
_CODE_TEXT_RE = re.compile(
    r"(?:\beval\s*\(|\bexec\s*\(|\bfunction\s*\(|=>|"
    r"\bimport\s+[A-Za-z_]|\brequire\s*\(|\bos\.system\s*\()",
    re.IGNORECASE,
)
_HOST_RE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_CONTROL_TYPES = frozenset(
    {
        "diagnostic",
        "diagnostics",
        "mock",
        "placeholder",
        "run-report",
        "run_report",
        "receipt",
        "stats",
        "paywall",
        "payment-required",
        "payment_required",
        "upgrade-required",
        "upgrade_required",
    }
)
_EMPTY_TYPES = frozenset({"empty", "no-results", "no_results"})


class ActorManifestError(RuntimeError):
    """Safe, stable failure raised by the manifest boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        self.code = str(code)
        self.retryable = bool(retryable)
        super().__init__(message)


class ManifestReference(BaseModel):
    """An exact runtime value reference; interpolation is not supported."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    ref: str = Field(alias="$ref")

    @field_validator("ref")
    @classmethod
    def _known_reference(cls, value: str) -> str:
        if value not in ALLOWED_REFERENCES:
            raise ValueError("manifest input contains an unknown reference")
        return value


class OutputFieldMapping(BaseModel):
    """One normalized output field sourced from bounded JSON pointers."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    pointers: tuple[str, ...] = Field(min_length=1, max_length=16)
    transforms: tuple[str, ...] = ()

    @field_validator("pointers")
    @classmethod
    def _valid_pointers(cls, pointers: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(pointers)) != len(pointers):
            raise ValueError("output pointers must be unique")
        for pointer in pointers:
            validate_json_pointer(pointer)
        return pointers

    @field_validator("transforms")
    @classmethod
    def _valid_transforms(cls, transforms: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(transforms)) != len(transforms):
            raise ValueError("output transforms must be unique")
        if any(transform not in ALLOWED_TRANSFORMS for transform in transforms):
            raise ValueError("output mapping contains an unknown transform")
        if "pick_first" in transforms and transforms[0] != "pick_first":
            raise ValueError("pick_first must be the first transform")
        return transforms

    @model_validator(mode="after")
    def _selection_is_explicit(self) -> "OutputFieldMapping":
        if len(self.pointers) > 1 and (
            not self.transforms or self.transforms[0] != "pick_first"
        ):
            raise ValueError("multiple pointers require pick_first")
        if len(self.pointers) == 1 and "pick_first" in self.transforms:
            raise ValueError("pick_first requires multiple pointers")
        return self


OutputFieldName = Literal[
    "native_id",
    "url",
    "published_at",
    "title",
    "text",
    "author",
    "author_handle",
    "source_name",
    "source_native_id",
    "source_url",
    "author_avatar_url",
    "thumbnail_url",
    "like_count",
    "comment_count",
    "repost_count",
    "share_count",
    "view_count",
]


class ManifestOutputMapping(BaseModel):
    """The fixed service content contract exposed by Manifest v1."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    native_id: OutputFieldMapping
    url: OutputFieldMapping
    published_at: OutputFieldMapping
    title: OutputFieldMapping | None = None
    text: OutputFieldMapping | None = None
    author: OutputFieldMapping | None = None
    author_handle: OutputFieldMapping | None = None
    source_name: OutputFieldMapping | None = None
    source_native_id: OutputFieldMapping | None = None
    source_url: OutputFieldMapping | None = None
    author_avatar_url: OutputFieldMapping | None = None
    thumbnail_url: OutputFieldMapping | None = None
    like_count: OutputFieldMapping | None = None
    comment_count: OutputFieldMapping | None = None
    repost_count: OutputFieldMapping | None = None
    share_count: OutputFieldMapping | None = None
    view_count: OutputFieldMapping | None = None

    @model_validator(mode="after")
    def _has_human_content(self) -> "ManifestOutputMapping":
        if self.title is None and self.text is None:
            raise ValueError("output requires title or text")
        pointer_count = sum(
            len(mapping.pointers)
            for mapping in self._mapping_values()
        )
        if pointer_count > MAX_OUTPUT_POINTERS:
            raise ValueError("manifest output contains too many pointers")
        return self

    def _mapping_values(self) -> tuple[OutputFieldMapping, ...]:
        values: list[OutputFieldMapping] = []
        for name in type(self).model_fields:
            mapping = getattr(self, name)
            if mapping is not None:
                values.append(mapping)
        return tuple(values)


class IdentityRule(BaseModel):
    """A mandatory source identity proof for every accepted output row."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    output_field: Literal["author_handle", "source_native_id", "source_url"]
    target_ref: Literal[
        "target.canonical_url",
        "target.native_id",
        "target.handle",
    ]
    match: Literal["exact", "handle", "url"] = "exact"

    @model_validator(mode="after")
    def _compatible_match(self) -> "IdentityRule":
        if self.match == "handle" and self.target_ref != "target.handle":
            raise ValueError("handle matching requires target.handle")
        if self.match == "url" and self.target_ref != "target.canonical_url":
            raise ValueError("url matching requires target.canonical_url")
        return self


class EmptyResultMarker(BaseModel):
    """An additive explicit-empty marker; built-in markers always remain active."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    pointer: str
    equals: str | int | float | bool

    @field_validator("pointer")
    @classmethod
    def _valid_pointer(cls, pointer: str) -> str:
        validate_json_pointer(pointer)
        return pointer


class SemanticValidation(BaseModel):
    """Non-disableable semantic checks plus narrow route-specific evidence."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    identity: IdentityRule
    url_host_allowlist: tuple[str, ...] = Field(min_length=1, max_length=12)
    empty_result_markers: tuple[EmptyResultMarker, ...] = Field(
        default=(),
        max_length=12,
    )

    @field_validator("url_host_allowlist")
    @classmethod
    def _valid_hosts(cls, hosts: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for raw_host in hosts:
            host = str(raw_host).strip().lower().rstrip(".")
            if (
                not _HOST_RE.fullmatch(host)
                or host == "localhost"
                or host.endswith(".localhost")
            ):
                raise ValueError("semantic URL host allowlist is invalid")
            try:
                ipaddress.ip_address(host)
            except ValueError:
                pass
            else:
                raise ValueError("semantic URL host must be a platform hostname")
            if host not in normalized:
                normalized.append(host)
        return tuple(normalized)


class ActorManifestV1(BaseModel):
    """A fully validated, code-free Actor adapter revision."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    version: Literal[1] = MANIFEST_VERSION
    actor_id: str
    build_number: str
    input_template: dict[str, Any] = Field(alias="input")
    output: ManifestOutputMapping
    semantics: SemanticValidation

    @model_validator(mode="before")
    @classmethod
    def _bounded_document(cls, value: Any) -> Any:
        _validate_manifest_document(value)
        return value

    @field_validator("actor_id")
    @classmethod
    def _valid_actor_id(cls, value: str) -> str:
        normalized = str(value).strip().replace("~", "/")
        if not _ACTOR_ID_RE.fullmatch(normalized):
            raise ValueError("actor_id must be a stable public Actor identifier")
        return normalized

    @field_validator("build_number")
    @classmethod
    def _exact_build_number(cls, value: str) -> str:
        normalized = str(value).strip()
        if not _BUILD_NUMBER_RE.fullmatch(normalized):
            raise ValueError("build_number must be an exact successful build number")
        return normalized

    @field_validator("input_template")
    @classmethod
    def _safe_input_template(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_input_template(value)
        return value

    @model_validator(mode="after")
    def _identity_field_is_mapped(self) -> "ActorManifestV1":
        field_name = self.semantics.identity.output_field
        if getattr(self.output, field_name) is None:
            raise ValueError("semantic identity output field is not mapped")
        return self


class ActorTarget(BaseModel):
    """Ephemeral source identity exposed to a manifest renderer."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    canonical_url: str | None = None
    native_id: str | None = Field(default=None, max_length=512)
    handle: str | None = Field(default=None, max_length=256)

    @field_validator("canonical_url")
    @classmethod
    def _safe_canonical_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_http_url(value)

    @field_validator("native_id", "handle")
    @classmethod
    def _nonempty_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("target identity must not be empty")
        if any(marker in normalized for marker in _TEMPLATE_MARKERS):
            raise ValueError("target identity contains template syntax")
        return normalized


class ActorRuntime(BaseModel):
    """Bounded runtime values frozen by a paid Actor validation plan."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    max_items: int = Field(default=1, ge=1, le=100)
    since_iso: str | None = None
    until_iso: str | None = None

    @field_validator("since_iso", "until_iso")
    @classmethod
    def _valid_timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _parse_datetime(value).isoformat()

    @model_validator(mode="after")
    def _ordered_window(self) -> "ActorRuntime":
        if (
            self.since_iso is not None
            and self.until_iso is not None
            and _parse_datetime(self.since_iso) > _parse_datetime(self.until_iso)
        ):
            raise ValueError("runtime time window is reversed")
        return self


class MappedActorItem(BaseModel):
    """One normalized row emitted by the restricted mapper."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    native_id: str = Field(min_length=1, max_length=512)
    url: str = Field(min_length=1, max_length=2_048)
    published_at: datetime
    title: str | None = Field(default=None, max_length=2_048)
    text: str | None = Field(default=None, max_length=100_000)
    author: str | None = Field(default=None, max_length=2_048)
    author_handle: str | None = Field(default=None, max_length=512)
    source_name: str | None = Field(default=None, max_length=2_048)
    source_native_id: str | None = Field(default=None, max_length=512)
    source_url: str | None = Field(default=None, max_length=2_048)
    author_avatar_url: str | None = Field(default=None, max_length=2_048)
    thumbnail_url: str | None = Field(default=None, max_length=2_048)
    like_count: int | float | None = None
    comment_count: int | float | None = None
    repost_count: int | float | None = None
    share_count: int | float | None = None
    view_count: int | float | None = None

    @model_validator(mode="after")
    def _content_and_metrics(self) -> "MappedActorItem":
        self.title = _nonempty_text(self.title)
        self.text = _nonempty_text(self.text)
        if self.title is None and self.text is None:
            raise ValueError("mapped item requires a nonempty title or text")
        for name in (
            "like_count",
            "comment_count",
            "repost_count",
            "share_count",
            "view_count",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ValueError("engagement metrics must be finite and nonnegative")
        return self


@dataclass(frozen=True, slots=True)
class ManifestMappingResult:
    """Normalized rows and their safe semantic outcome."""

    items: tuple[MappedActorItem, ...]
    semantic_outcome: Literal[
        "valid_nonempty",
        "valid_empty",
        "suspicious_empty",
    ]
    excluded_rows: int = 0
    latest_published_at: str | None = None
    latest_native_id: str | None = None


def parse_actor_manifest(value: Any) -> ActorManifestV1:
    """Validate untrusted AI JSON and return a strict Manifest v1 model."""

    if isinstance(value, ActorManifestV1):
        return value
    if isinstance(value, (bytes, bytearray)):
        if len(value) > MAX_MANIFEST_BYTES:
            raise ActorManifestError(
                "apify_manifest_too_large",
                "Actor Manifest exceeds the size limit",
            )
        try:
            value = json.loads(bytes(value))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ActorManifestError(
                "apify_manifest_invalid_json",
                "Actor Manifest is not valid JSON",
            ) from None
    elif isinstance(value, str):
        if len(value.encode("utf-8")) > MAX_MANIFEST_BYTES:
            raise ActorManifestError(
                "apify_manifest_too_large",
                "Actor Manifest exceeds the size limit",
            )
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            raise ActorManifestError(
                "apify_manifest_invalid_json",
                "Actor Manifest is not valid JSON",
            ) from None
    try:
        return ActorManifestV1.model_validate(value)
    except (ValidationError, TypeError, ValueError):
        raise ActorManifestError(
            "apify_manifest_invalid",
            "Actor Manifest failed static validation",
        ) from None


def canonical_manifest_json(manifest: ActorManifestV1 | Mapping[str, Any] | str) -> str:
    """Return the immutable canonical JSON used for hashing and storage."""

    parsed = parse_actor_manifest(manifest)
    return json.dumps(
        parsed.model_dump(mode="json", by_alias=True, exclude_none=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def actor_manifest_hash(
    manifest: ActorManifestV1 | Mapping[str, Any] | str,
) -> str:
    return hashlib.sha256(
        canonical_manifest_json(manifest).encode("utf-8")
    ).hexdigest()


def render_actor_input(
    manifest: ActorManifestV1 | Mapping[str, Any] | str,
    target: ActorTarget | Mapping[str, Any],
    runtime: ActorRuntime | Mapping[str, Any],
) -> dict[str, Any]:
    """Render JSON input by exact reference replacement, without interpolation."""

    parsed = parse_actor_manifest(manifest)
    target_model = _validated_model(
        ActorTarget,
        target,
        code="apify_manifest_target_invalid",
        message="Actor target failed validation",
    )
    runtime_model = _validated_model(
        ActorRuntime,
        runtime,
        code="apify_manifest_runtime_invalid",
        message="Actor runtime values failed validation",
    )
    values = {
        "target.canonical_url": target_model.canonical_url,
        "target.native_id": target_model.native_id,
        "target.handle": target_model.handle,
        "runtime.max_items": runtime_model.max_items,
        "runtime.since_iso": runtime_model.since_iso,
        "runtime.until_iso": runtime_model.until_iso,
    }

    def render(value: Any) -> Any:
        if isinstance(value, dict):
            if "$ref" in value:
                try:
                    reference = ManifestReference.model_validate(value)
                except ValidationError:
                    raise ActorManifestError(
                        "apify_manifest_reference_invalid",
                        "Actor Manifest contains an invalid runtime reference",
                    ) from None
                resolved = values[reference.ref]
                if resolved is None:
                    raise ActorManifestError(
                        "apify_manifest_reference_unavailable",
                        "Actor Manifest requires unavailable target context",
                    )
                return resolved
            return {key: render(child) for key, child in value.items()}
        if isinstance(value, list):
            return [render(child) for child in value]
        return value

    rendered = render(parsed.input_template)
    if not isinstance(rendered, dict):
        raise ActorManifestError(
            "apify_manifest_input_invalid",
            "Rendered Actor input must be a JSON object",
        )
    return rendered


def map_actor_output(
    manifest: ActorManifestV1 | Mapping[str, Any] | str,
    rows: Sequence[Mapping[str, Any]],
    target: ActorTarget | Mapping[str, Any],
    runtime: ActorRuntime | Mapping[str, Any],
) -> ManifestMappingResult:
    """Map bounded Dataset rows and enforce identity, URL, and time semantics."""

    parsed = parse_actor_manifest(manifest)
    target_model = _validated_model(
        ActorTarget,
        target,
        code="apify_manifest_target_invalid",
        message="Actor target failed validation",
    )
    runtime_model = _validated_model(
        ActorRuntime,
        runtime,
        code="apify_manifest_runtime_invalid",
        message="Actor runtime values failed validation",
    )
    if isinstance(rows, (str, bytes, bytearray)) or not isinstance(rows, Sequence):
        raise ActorManifestError(
            "apify_actor_contract_mismatch",
            "Actor Dataset must be a JSON row array",
            retryable=True,
        )
    if len(rows) > MAX_DATASET_ROWS:
        raise ActorManifestError(
            "apify_actor_dataset_row_limit",
            "Actor Dataset exceeded the row limit",
            retryable=True,
        )
    if not rows:
        return ManifestMappingResult((), "suspicious_empty")

    mapped: list[MappedActorItem] = []
    latest_observed_item: MappedActorItem | None = None
    latest_mapped_item: MappedActorItem | None = None
    excluded = 0
    metadata_only = 0
    explicit_empty = 0
    window_excluded = 0
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            raise ActorManifestError(
                "apify_actor_contract_mismatch",
                "Actor Dataset contains a non-object row",
                retryable=True,
            )
        row = dict(raw_row)
        target_error = _target_control_error(row)
        if target_error is not None:
            raise ActorManifestError(
                target_error,
                "Actor reported a target-scoped availability condition",
                retryable=False,
            )
        if _is_placeholder_or_control(row):
            excluded += 1
            continue
        if _is_explicit_empty(row, parsed.semantics.empty_result_markers):
            _validate_empty_identity(
                row,
                output=parsed.output,
                semantics=parsed.semantics,
                target=target_model,
            )
            explicit_empty += 1
            continue
        values: dict[str, Any] = {}
        for name in type(parsed.output).model_fields:
            mapping = getattr(parsed.output, name)
            if mapping is None:
                continue
            try:
                value = _apply_output_mapping(row, mapping)
            except ActorManifestError:
                raise
            except (TypeError, ValueError, OverflowError):
                raise ActorManifestError(
                    "apify_actor_contract_mismatch",
                    "Actor output could not be normalized",
                    retryable=True,
                ) from None
            if value is not None:
                values[name] = value
        try:
            item = MappedActorItem.model_validate(values)
        except ValidationError:
            if _is_metadata_only_mapping(values):
                metadata_only += 1
                continue
            raise ActorManifestError(
                "apify_actor_contract_mismatch",
                "Actor output does not satisfy the content contract",
                retryable=True,
            ) from None
        validation_runtime = runtime_model.model_copy(
            update={"since_iso": None, "until_iso": None}
        )
        _validate_mapped_item(
            item,
            semantics=parsed.semantics,
            target=target_model,
            runtime=validation_runtime,
        )
        if latest_observed_item is None or (
            item.published_at,
            item.native_id,
        ) > (
            latest_observed_item.published_at,
            latest_observed_item.native_id,
        ):
            latest_observed_item = item
        if (
            runtime_model.since_iso
            and item.published_at < _parse_datetime(runtime_model.since_iso)
        ) or (
            runtime_model.until_iso
            and item.published_at > _parse_datetime(runtime_model.until_iso)
        ):
            window_excluded += 1
            continue
        mapped.append(item)
        if latest_mapped_item is None or (
            item.published_at,
            item.native_id,
        ) > (
            latest_mapped_item.published_at,
            latest_mapped_item.native_id,
        ):
            latest_mapped_item = item

    if mapped:
        return ManifestMappingResult(
            tuple(mapped),
            "valid_nonempty",
            excluded_rows=(
                excluded + explicit_empty + metadata_only + window_excluded
            ),
            latest_published_at=(
                latest_mapped_item.published_at.isoformat()
                if latest_mapped_item
                else None
            ),
            latest_native_id=(
                latest_mapped_item.native_id if latest_mapped_item else None
            ),
        )
    if explicit_empty and explicit_empty + excluded + metadata_only == len(rows):
        return ManifestMappingResult(
            (),
            "valid_empty",
            excluded_rows=excluded + metadata_only,
        )
    if window_excluded and (
        window_excluded + explicit_empty + excluded + metadata_only == len(rows)
    ):
        return ManifestMappingResult(
            (),
            "valid_empty",
            excluded_rows=excluded + explicit_empty + metadata_only + window_excluded,
            latest_published_at=(
                latest_observed_item.published_at.isoformat()
                if latest_observed_item
                else None
            ),
            latest_native_id=(
                latest_observed_item.native_id
                if latest_observed_item
                else None
            ),
        )
    if excluded == len(rows):
        raise ActorManifestError(
            "apify_actor_placeholder",
            "Actor returned only placeholder or control rows",
            retryable=True,
        )
    if metadata_only and metadata_only + excluded == len(rows):
        raise ActorManifestError(
            "apify_actor_metadata_only",
            "Actor returned metadata rows without content items",
            retryable=True,
        )
    raise ActorManifestError(
        "apify_actor_contract_mismatch",
        "Actor output contains no valid content rows",
        retryable=True,
    )


def summarize_json_paths(
    value: Any,
    *,
    max_depth: int = 6,
    max_paths: int = 256,
    max_bytes: int = 8 * 1024,
) -> dict[str, Any]:
    """Return only field paths and JSON types; never return field values."""

    bounded_depth = max(1, min(int(max_depth), 12))
    bounded_paths = max(1, min(int(max_paths), 512))
    bounded_bytes = max(256, min(int(max_bytes), 64 * 1024))
    observed: dict[str, set[str]] = {}
    truncated = False

    def visit(node: Any, path: str, depth: int) -> None:
        nonlocal truncated
        if len(observed) >= bounded_paths:
            truncated = True
            return
        type_name = _json_type(node)
        if path:
            observed.setdefault(path, set()).add(type_name)
        if depth >= bounded_depth:
            if isinstance(node, (dict, list)) and node:
                truncated = True
            return
        if isinstance(node, Mapping):
            for key, child in node.items():
                if not isinstance(key, str):
                    truncated = True
                    continue
                token = key.replace("~", "~0").replace("/", "~1")
                visit(child, f"{path}/{token}", depth + 1)
                if len(observed) >= bounded_paths:
                    break
        elif isinstance(node, Sequence) and not isinstance(
            node,
            (str, bytes, bytearray),
        ):
            for child in node[:8]:
                visit(child, f"{path}/[]", depth + 1)
                if len(observed) >= bounded_paths:
                    break
            if len(node) > 8:
                truncated = True

    visit(value, "", 0)
    entries = [
        {
            "path": path,
            "type": (
                next(iter(types))
                if len(types) == 1
                else "mixed"
            ),
        }
        for path, types in sorted(observed.items())
    ]
    payload = {
        "root_type": _json_type(value),
        "paths": entries,
        "truncated": truncated,
    }
    while (
        len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        > bounded_bytes
        and payload["paths"]
    ):
        payload["paths"].pop()
        payload["truncated"] = True
    return payload


def validate_json_pointer(pointer: str) -> str:
    """Validate the strict RFC 6901 subset used by Manifest v1."""

    if (
        not isinstance(pointer, str)
        or not pointer
        or len(pointer) > MAX_POINTER_CHARS
        or not pointer.startswith("/")
        or _POINTER_ESCAPE_RE.search(pointer)
    ):
        raise ValueError("output mapping contains an invalid RFC 6901 pointer")
    if any(ord(character) < 0x20 for character in pointer):
        raise ValueError("output pointer contains control characters")
    return pointer


_MISSING_POINTER = object()


def resolve_json_pointer(
    document: Any,
    pointer: str,
    *,
    default: Any = None,
) -> Any:
    validate_json_pointer(pointer)
    current = document
    for raw_token in pointer.split("/")[1:]:
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                return default
            current = current[token]
            continue
        if isinstance(current, Sequence) and not isinstance(
            current,
            (str, bytes, bytearray),
        ):
            if not token.isdigit():
                return default
            index = int(token)
            if index >= len(current):
                return default
            current = current[index]
            continue
        return default
    return current


def normalize_http_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 2_048:
        raise ValueError("URL is empty or too long")
    parsed = urlsplit(text)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("URL must be credential-free HTTP(S)")
    try:
        port = parsed.port
    except ValueError:
        raise ValueError("URL port is invalid") from None
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("URL hostname is not public")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        raise ValueError("URL hostname must preserve a public platform identity")
    default_port = (
        parsed.scheme.lower() == "http" and port == 80
    ) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    authority = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path or "/"
    return urlunsplit(
        (
            parsed.scheme.lower(),
            authority,
            path,
            parsed.query,
            "",
        )
    )


def _validated_model(
    model_type: type[BaseModel],
    value: BaseModel | Mapping[str, Any],
    *,
    code: str,
    message: str,
) -> Any:
    if isinstance(value, model_type):
        return value
    try:
        return model_type.model_validate(value)
    except ValidationError:
        raise ActorManifestError(code, message) from None


def _validate_manifest_document(value: Any) -> None:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError):
        raise ValueError("manifest must contain only finite JSON values") from None
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValueError("manifest exceeds the size limit")


def _validate_input_template(value: Any) -> None:
    node_count = 0

    def visit(node: Any, *, depth: int, under_url_key: bool = False) -> None:
        nonlocal node_count
        node_count += 1
        if node_count > MAX_INPUT_NODES or depth > MAX_INPUT_DEPTH:
            raise ValueError("manifest input exceeds structural limits")
        if node is None or isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            if isinstance(node, float) and not math.isfinite(node):
                raise ValueError("manifest input contains a non-finite number")
            return
        if isinstance(node, str):
            if (
                len(node) > MAX_INPUT_STRING_CHARS
                or any(marker in node for marker in _TEMPLATE_MARKERS)
                or _CODE_TEXT_RE.search(node)
                or "://" in node
            ):
                raise ValueError("manifest input contains forbidden literal text")
            if under_url_key:
                raise ValueError(
                    "URL-shaped input fields require target.canonical_url"
                )
            return
        if isinstance(node, list):
            for child in node:
                visit(child, depth=depth + 1, under_url_key=under_url_key)
            return
        if not isinstance(node, dict):
            raise ValueError("manifest input contains a non-JSON value")
        if "$ref" in node:
            try:
                reference = ManifestReference.model_validate(node)
            except ValidationError:
                raise ValueError("manifest input reference is invalid") from None
            if under_url_key and reference.ref != "target.canonical_url":
                raise ValueError(
                    "URL-shaped input fields require target.canonical_url"
                )
            return
        for raw_key, child in node.items():
            if not isinstance(raw_key, str) or not raw_key or len(raw_key) > 128:
                raise ValueError("manifest input key is invalid")
            normalized = re.sub(r"[^a-z0-9_]", "", raw_key.casefold())
            if any(part in normalized for part in _FORBIDDEN_INPUT_KEY_PARTS):
                raise ValueError("manifest input contains a forbidden field")
            url_key = under_url_key or "url" in normalized or "uri" in normalized
            visit(child, depth=depth + 1, under_url_key=url_key)

    if not isinstance(value, dict):
        raise ValueError("manifest input must be a JSON object")
    visit(value, depth=0)


def _apply_output_mapping(
    row: Mapping[str, Any],
    mapping: OutputFieldMapping,
) -> Any:
    values = [resolve_json_pointer(row, pointer) for pointer in mapping.pointers]
    value = (
        next((candidate for candidate in values if not _is_empty(candidate)), None)
        if len(values) > 1
        else values[0]
    )
    for transform in mapping.transforms:
        if transform == "pick_first":
            continue
        if value is None:
            break
        if transform == "to_string":
            if isinstance(value, (dict, list)):
                raise TypeError("objects cannot be converted to strings")
            value = str(value).strip()
        elif transform == "to_integer":
            if isinstance(value, bool):
                raise TypeError("booleans cannot be converted to integers")
            value = int(value)
        elif transform == "to_number":
            if isinstance(value, bool):
                raise TypeError("booleans cannot be converted to numbers")
            value = float(value)
            if not math.isfinite(value):
                raise ValueError("number is not finite")
        elif transform == "to_boolean":
            value = _to_boolean(value)
        elif transform == "parse_datetime":
            value = _parse_datetime(value)
        elif transform == "normalize_url":
            value = normalize_http_url(value)
        elif transform == "strip_html":
            value = _strip_html(value)
        else:  # pragma: no cover - model validation makes this unreachable.
            raise ValueError("unknown transform")
    return None if _is_empty(value) else value


def _validate_mapped_item(
    item: MappedActorItem,
    *,
    semantics: SemanticValidation,
    target: ActorTarget,
    runtime: ActorRuntime,
) -> None:
    try:
        item.url = normalize_http_url(item.url)
        for field_name in (
            "source_url",
            "author_avatar_url",
            "thumbnail_url",
        ):
            value = getattr(item, field_name)
            if value is not None:
                setattr(item, field_name, normalize_http_url(value))
    except ValueError:
        raise ActorManifestError(
            "apify_actor_output_url_invalid",
            "Actor output contains an invalid URL",
            retryable=True,
        ) from None
    host = (urlsplit(item.url).hostname or "").lower().rstrip(".")
    if not any(
        host == allowed or host.endswith(f".{allowed}")
        for allowed in semantics.url_host_allowlist
    ):
        raise ActorManifestError(
            "apify_actor_output_host_disallowed",
            "Actor output URL does not match the route host policy",
            retryable=True,
        )
    published = item.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    else:
        published = published.astimezone(timezone.utc)
    item.published_at = published
    if runtime.since_iso and published < _parse_datetime(runtime.since_iso):
        raise ActorManifestError(
            "apify_actor_output_outside_window",
            "Actor output is outside the requested time window",
            retryable=True,
        )
    if runtime.until_iso and published > _parse_datetime(runtime.until_iso):
        raise ActorManifestError(
            "apify_actor_output_outside_window",
            "Actor output is outside the requested time window",
            retryable=True,
        )
    rule = semantics.identity
    actual = getattr(item, rule.output_field)
    expected = {
        "target.canonical_url": target.canonical_url,
        "target.native_id": target.native_id,
        "target.handle": target.handle,
    }[rule.target_ref]
    if actual is None or expected is None or not _identity_matches(
        actual,
        expected,
        mode=rule.match,
    ):
        raise ActorManifestError(
            "apify_actor_target_identity_mismatch",
            "Actor output does not match the requested target identity",
            retryable=True,
        )


def _identity_matches(actual: Any, expected: Any, *, mode: str) -> bool:
    if mode == "handle":
        return _normalize_handle(actual) == _normalize_handle(expected)
    if mode == "url":
        try:
            left = urlsplit(normalize_http_url(actual))
            right = urlsplit(normalize_http_url(expected))
        except ValueError:
            return False
        return (
            left.scheme == right.scheme
            and left.netloc == right.netloc
            and left.path.rstrip("/") == right.path.rstrip("/")
            and sorted(parse_qsl(left.query, keep_blank_values=True))
            == sorted(parse_qsl(right.query, keep_blank_values=True))
        )
    return str(actual).strip() == str(expected).strip()


def _validate_empty_identity(
    row: Mapping[str, Any],
    *,
    output: ManifestOutputMapping,
    semantics: SemanticValidation,
    target: ActorTarget,
) -> None:
    rule = semantics.identity
    mapping = getattr(output, rule.output_field)
    try:
        actual = _apply_output_mapping(row, mapping)
    except (ActorManifestError, TypeError, ValueError, OverflowError):
        actual = None
    expected = {
        "target.canonical_url": target.canonical_url,
        "target.native_id": target.native_id,
        "target.handle": target.handle,
    }[rule.target_ref]
    if actual is None or expected is None or not _identity_matches(
        actual,
        expected,
        mode=rule.match,
    ):
        raise ActorManifestError(
            "apify_actor_target_identity_mismatch",
            "Actor empty result does not match the requested target identity",
            retryable=True,
        )


def _normalize_handle(value: Any) -> str:
    text = str(value or "").strip()
    if "://" in text:
        parsed = urlsplit(text)
        text = parsed.path.strip("/").split("/", 1)[0]
    return text.lstrip("@").strip().casefold()


def _is_placeholder_or_control(row: Mapping[str, Any]) -> bool:
    for key in (
        "demo",
        "isDemo",
        "is_demo",
        "mock",
        "isMock",
        "is_mock",
        "placeholder",
        "paywall",
        "isPaywalled",
        "is_paywalled",
        "paymentRequired",
        "payment_required",
    ):
        if row.get(key) is True:
            return True
    row_type = str(
        row.get("resultType")
        or row.get("result_type")
        or row.get("recordType")
        or row.get("record_type")
        or row.get("type")
        or ""
    ).strip().casefold()
    if row_type in _CONTROL_TYPES:
        return True
    control_text = " ".join(
        str(row.get(key) or "")
        for key in (
            "error",
            "message",
            "notice",
            "statusMessage",
            "warning",
            "status",
        )
    ).casefold()
    return any(
        marker in control_text
        for marker in (
            "demo mode",
            "placeholder",
            "mock data",
            "payment required",
            "upgrade your plan",
        )
    )


def _target_control_error(row: Mapping[str, Any]) -> str | None:
    """Classify only fixed control fields; never inspect mapped content text."""

    control = " ".join(
        str(row.get(key) or "")
        for key in (
            "error",
            "errorCode",
            "error_code",
            "message",
            "status",
            "statusMessage",
            "resultType",
            "result_type",
        )
    ).strip().casefold()
    if not control:
        return None
    if any(
        marker in control
        for marker in (
            "account is private",
            "profile is private",
            "private account",
            "private profile",
            "target_private",
        )
    ):
        return "apify_actor_target_private"
    if any(
        marker in control
        for marker in (
            "account deleted",
            "profile deleted",
            "target_deleted",
        )
    ):
        return "apify_actor_target_deleted"
    if any(
        marker in control
        for marker in (
            "account not found",
            "profile not found",
            "user not found",
            "no such account",
            "does not exist",
            "target_not_found",
        )
    ):
        return "apify_actor_target_not_found"
    return None


def _is_explicit_empty(
    row: Mapping[str, Any],
    markers: Sequence[EmptyResultMarker],
) -> bool:
    if row.get("noResults") is True or row.get("no_results") is True:
        return True
    row_type = str(
        row.get("resultType")
        or row.get("result_type")
        or row.get("type")
        or ""
    ).strip().casefold()
    if row_type in _EMPTY_TYPES:
        return True
    return any(
        resolve_json_pointer(
            row,
            marker.pointer,
            default=_MISSING_POINTER,
        )
        == marker.equals
        for marker in markers
    )


def _is_empty(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and not value.strip()
    )


def _nonempty_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _is_metadata_only_mapping(values: Mapping[str, Any]) -> bool:
    """Return true when a row maps identity metadata but no content fields."""

    return not any(
        values.get(field_name) is not None
        for field_name in (
            "native_id",
            "url",
            "published_at",
            "title",
            "text",
        )
    )


def _to_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    normalized = str(value).strip().casefold()
    if normalized in {"true", "yes"}:
        return True
    if normalized in {"false", "no"}:
        return False
    raise ValueError("value cannot be converted to boolean")


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, bool):
        raise TypeError("datetime must not be a boolean")
    if isinstance(value, (int, float)):
        return _parse_epoch_datetime(value)
    if not isinstance(value, str) or not value.strip():
        raise TypeError("datetime must be a nonempty string or epoch number")
    normalized = value.strip()
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", normalized):
        return _parse_epoch_datetime(float(normalized))
    parsed = isoparse(normalized)
    if parsed.tzinfo is None:
        raise ValueError("datetime must include a timezone")
    return parsed.astimezone(timezone.utc)


def _parse_epoch_datetime(value: int | float) -> datetime:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("epoch datetime must be finite and nonnegative")
    # Actor schemas commonly expose Unix seconds or milliseconds.  Values
    # beyond the supported UTC window are treated as milliseconds exactly
    # once; accepting arbitrary magnitudes would hide contract drift.
    max_epoch_seconds = 4_102_444_800  # 2100-01-01T00:00:00Z
    if number > max_epoch_seconds:
        number /= 1_000
    if number < 946_684_800 or number > max_epoch_seconds:
        raise ValueError("epoch datetime is outside the supported range")
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise ValueError("epoch datetime is invalid") from None


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: list[str] = []

    def handle_data(self, data: str) -> None:
        self.values.append(data)


def _strip_html(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("strip_html requires a string")
    parser = _TextExtractor()
    parser.feed(value[:100_000])
    parser.close()
    return " ".join(
        html.unescape("".join(parser.values)).split()
    )


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        return "array"
    return "unknown"


def actor_manifest_capability_error(
    manifest: ActorManifestV1 | Mapping[str, Any], *, platform: str | None = None, target_type: str, capability: str,
) -> str | None:
    """Return a deterministic incompatibility without reading Dataset values."""

    parsed = parse_actor_manifest(manifest)
    if target_type not in {"profile", "channel"} or capability != "items":
        return None
    if (platform, target_type, capability) == ("youtube", "channel", "items") and (parsed.semantics.identity.target_ref == "target.handle" or '"target.handle"' in json.dumps(parsed.input_template, sort_keys=True)):
        return "apify_manifest_youtube_channel_identity_unverifiable"
    for mapping in (parsed.output.native_id, parsed.output.url):
        if mapping is None:
            continue
        if all(_pointer_is_source_identity(pointer) for pointer in mapping.pointers):
            return "apify_manifest_item_identity_invalid"
    return None


def actor_pricing_capability_error(
    pricing: Mapping[str, Any],
    *,
    platform: str,
    target_type: str,
    capability: str,
) -> str | None:
    """Use only strong price-event evidence to reject metadata-only Actors."""

    if (platform, target_type, capability) != (
        "youtube",
        "channel",
        "items",
    ):
        return None
    pricing_per_event = pricing.get("pricingPerEvent")
    events = (
        pricing_per_event.get("actorChargeEvents")
        if isinstance(pricing_per_event, Mapping)
        else None
    )
    if not isinstance(events, Mapping):
        return None
    names = [
        re.sub(r"[^a-z0-9]+", "-", str(name).casefold()).strip("-")
        for name in events
        if str(name).strip()
    ]
    substantive = [
        name
        for name in names
        if name not in {"actor-start", "apify-actor-start", "run-start"}
    ]
    if not substantive or any(
        any(marker in name for marker in ("video", "dataset-item"))
        for name in substantive
    ):
        return None
    metadata_markers = (
        "channel",
        "profile",
        "statistic",
        "subscriber",
        "enrichment",
        "description-link",
    )
    if all(
        any(marker in name for marker in metadata_markers)
        for name in substantive
    ):
        return "actor_items_capability_unproven"
    return None


def _pointer_is_source_identity(pointer: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "", pointer.casefold())
    if any(
        marker in normalized
        for marker in ("video", "post", "tweet", "item", "media", "short", "reel")
    ):
        return False
    return any(marker in normalized for marker in ("channel", "profile"))


__all__ = [
    "ALLOWED_REFERENCES",
    "ALLOWED_TRANSFORMS",
    "ActorManifestError",
    "ActorManifestV1",
    "ActorRuntime",
    "ActorTarget",
    "IdentityRule",
    "ManifestMappingResult",
    "MappedActorItem",
    "OutputFieldMapping",
    "SemanticValidation",
    "actor_manifest_hash",
    "actor_manifest_capability_error",
    "actor_pricing_capability_error",
    "canonical_manifest_json",
    "map_actor_output",
    "normalize_http_url",
    "parse_actor_manifest",
    "render_actor_input",
    "resolve_json_pointer",
    "summarize_json_paths",
    "validate_json_pointer",
]
