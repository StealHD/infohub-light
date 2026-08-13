"""Read-only source setup and Actor capability HTTP projections."""

from typing import Any

from fastapi import Depends, FastAPI, Response

from .context import ApiContext
from .responses import ok
from .system_auth import api_context, current_admin, current_user
from ..services.apify_actor_ops import supported_route_profiles
from ..services.source_type_registry import (
    YOUTUBE_CHANNEL_SETUP_TYPE,
    list_source_setup_types,
)


def _public_source_capability(route: dict[str, Any]) -> dict[str, Any]:
    platform = str(route["platform"])
    fields = (
        [
            {"name": "url", "input_type": "text", "required": True},
            {
                "name": "keep_latest_item",
                "input_type": "boolean",
                "required": False,
            },
        ]
        if platform == "youtube"
        else [
            {"name": "profile_id", "input_type": "select", "required": True},
            {"name": "target", "input_type": "text", "required": True},
        ]
    )
    return {
        "profile_id": str(route["route_id"]),
        "platform": platform,
        "target_type": str(route["target_type"]),
        "capability": str(route["capability"]),
        "mode": str(route["mode"]),
        "generation": int(route["generation"]),
        "storage_type": (
            YOUTUBE_CHANNEL_SETUP_TYPE
            if platform == "youtube"
            else "apify_social"
        ),
        "fields": fields,
    }


async def catalog_source_types(
    response: Response,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    generation, availability = context.source_setup_availability(
        str(user["workspace_id"])
    )
    response.headers["Cache-Control"] = "no-store"
    return ok(
        {
            "schema_version": 1,
            "generation": generation,
            "source_types": list_source_setup_types(availability=availability),
        }
    )


async def catalog_source_capabilities(
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    ops = context.apify_actor_ops_for(str(user["workspace_id"]))
    capabilities = [
        _public_source_capability(route)
        for route in ops.list_routes()
        if ops.source_capability_ready(str(route["route_id"]))
    ]
    response.headers["Cache-Control"] = "no-store"
    return ok(
        {
            "schema_version": 1,
            "generation": ops.catalog_generation(),
            "support_profiles": supported_route_profiles(),
            "capabilities": capabilities,
        }
    )


def register_catalog_metadata_routes(app: FastAPI) -> None:
    """Register catalog metadata routes in their stable order."""

    app.add_api_route(
        "/api/catalog/source-types", catalog_source_types, methods=["GET"]
    )
    app.add_api_route(
        "/api/catalog/source-capabilities",
        catalog_source_capabilities,
        methods=["GET"],
    )
