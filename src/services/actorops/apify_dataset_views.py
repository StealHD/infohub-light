"""Convert public Apify Dataset View declarations into a row schema."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


_FORMAT_SCHEMAS: dict[str, dict[str, str]] = {
    "boolean": {"type": "boolean"},
    "date": {"type": "string", "format": "date-time"},
    "image": {"type": "string", "format": "uri"},
    "link": {"type": "string", "format": "uri"},
    "number": {"type": "number"},
    "text": {"type": "string"},
}


def row_schema_from_dataset_views(dataset: object) -> Mapping[str, object]:
    if not isinstance(dataset, Mapping):
        return {}
    views = dataset.get("views")
    if not isinstance(views, Mapping):
        return {}
    properties: dict[str, object] = {}
    for view in views.values():
        if not isinstance(view, Mapping):
            continue
        display = view.get("display")
        display_properties = (
            display.get("properties") if isinstance(display, Mapping) else None
        )
        if isinstance(display_properties, Mapping):
            for field, definition in display_properties.items():
                _add_field(properties, field, definition)
        transformation = view.get("transformation")
        fields = (
            transformation.get("fields")
            if isinstance(transformation, Mapping)
            else None
        )
        if isinstance(fields, Sequence) and not isinstance(fields, (str, bytes)):
            for field in fields:
                _add_field(properties, field, None)
    return {"type": "object", "properties": properties} if properties else {}


def _add_field(
    properties: dict[str, object], field: object, definition: object
) -> None:
    name = str(field).strip() if isinstance(field, str) else ""
    if not name or len(name) > 128 or name in properties:
        return
    raw_format = definition.get("format") if isinstance(definition, Mapping) else None
    field_format = str(raw_format or "text").strip().casefold()
    properties[name] = dict(_FORMAT_SCHEMAS.get(field_format, {"type": "string"}))


__all__ = ["row_schema_from_dataset_views"]
