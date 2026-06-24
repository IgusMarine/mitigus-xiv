"""Auto-update do Mitigus (dados + app). Ver `updater.py`."""
from .updater import (
    MANIFEST_URL,
    apply_pending_update,
    app_update_available,
    fetch_manifest,
    stage_app_update,
    sync_data,
)

__all__ = [
    "MANIFEST_URL",
    "apply_pending_update",
    "app_update_available",
    "fetch_manifest",
    "stage_app_update",
    "sync_data",
]
