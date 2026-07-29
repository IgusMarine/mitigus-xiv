"""Auto-update do Mitigus (dados + app). Ver `updater.py` e `manual.py`."""
from .manual import (
    apply_drop_folder,
    apply_manual,
    drop_dir,
    manual_weave_path,
    parse_constants_cs,
)
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
    "apply_drop_folder",
    "apply_manual",
    "apply_pending_update",
    "app_update_available",
    "drop_dir",
    "fetch_manifest",
    "manual_weave_path",
    "parse_constants_cs",
    "stage_app_update",
    "sync_data",
]
