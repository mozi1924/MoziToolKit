"""Live Sync Material Subsystem."""

from .manager import (
    LiveSyncMaterialManager,
    ResolvedFaceTexture,
    PROP_PACK_HASH,
    PROP_PACK_HASH_SHORT,
    PROP_ATLAS_CHUNK_ID,
    PROP_ATLAS_MAPPING,
)
from .binding import (
    clear_shared_material_manager,
    get_shared_material_manager,
    rebind_mesh_material_indices,
    sync_section_material_slots,
    validate_and_sync_scene_materials,
)

__all__ = (
    "LiveSyncMaterialManager",
    "ResolvedFaceTexture",
    "PROP_PACK_HASH",
    "PROP_PACK_HASH_SHORT",
    "PROP_ATLAS_CHUNK_ID",
    "PROP_ATLAS_MAPPING",
    "clear_shared_material_manager",
    "get_shared_material_manager",
    "rebind_mesh_material_indices",
    "sync_section_material_slots",
    "validate_and_sync_scene_materials",
)
