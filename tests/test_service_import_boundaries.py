import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _module_loaded_after_import(imported: str, observed: str) -> bool:
    script = (
        "import importlib,sys;"
        f"importlib.import_module({imported!r});"
        f"print({observed!r} in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "True"


def test_service_store_import_does_not_eagerly_load_user_feed_store():
    assert not _module_loaded_after_import(
        "src.storage.service_store",
        "src.services.user_feed_store",
    )


def test_user_feed_store_import_does_not_load_service_store():
    assert not _module_loaded_after_import(
        "src.services.user_feed_store",
        "src.storage.service_store",
    )


def test_source_acquisition_keeps_projection_compatibility_exports():
    from src.services import source_acquisition, source_projection

    assert (
        source_acquisition.TargetSubscriptionProjection
        is source_projection.TargetSubscriptionProjection
    )
    assert (
        source_acquisition.target_subscription_projection
        is source_projection.target_subscription_projection
    )
