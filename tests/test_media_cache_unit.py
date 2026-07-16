from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import httpx

from src.services import media_cache
from src.storage.service_store import ServiceStore


def test_media_cache_download_uses_narrow_x_and_instagram_synthetic_dns_suffixes() -> None:
    response = httpx.Response(
        200,
        content=b"\x89PNG\r\n\x1a\nimage-bytes",
        headers={"content-type": "image/png"},
        request=httpx.Request("GET", "https://pbs.twimg.com/profile_images/avatar.png"),
    )
    fetch_public = AsyncMock(return_value=response)
    with TemporaryDirectory() as directory, patch.object(
        media_cache, "fetch_public_http", fetch_public
    ):
        media_cache.MediaCacheService(
            ServiceStore(Path(directory)), data_dir=directory
        )._download("https://pbs.twimg.com/profile_images/avatar.png")

    assert media_cache.X_MEDIA_HOST_SUFFIXES == ("pbs.twimg.com",)
    assert media_cache.TRUSTED_MEDIA_HOST_SUFFIXES == (
        "cdninstagram.com",
        "fbcdn.net",
        "pbs.twimg.com",
    )
    assert fetch_public.await_args.kwargs["synthetic_dns_host_suffixes"] == (
        "cdninstagram.com",
        "fbcdn.net",
        "pbs.twimg.com",
    )
