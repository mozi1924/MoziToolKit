"""One-shot material datablock migrations (addon upgrade path).

These run on addon registration and after loading a ``.blend`` file, and only touch
nodes that still carry a retired attribute name. They are idempotent.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("MoziToolKit.Materials.Migrations")

# Retired in the 2026-10 API prune: merged into `mtk_uv_transform` (single Float4
# face attribute in Rust, identical payload). Kept here so old .blend files can be
# repaired in place instead of silently losing UV tiling.
LEGACY_UV_TRANSFORM_ATTR = "mtk_uv_tiling_transform"
CANONICAL_UV_TRANSFORM_ATTR = "mtk_uv_transform"

_migration_handler = None


def migrate_legacy_uv_attribute_names() -> int:
    """Point legacy ``mtk_uv_tiling_transform`` shader attributes at the canonical name.

    Returns the number of renamed ``ShaderNodeAttribute`` nodes.
    """
    try:
        import bpy
    except ImportError:  # pragma: no cover - only reachable outside Blender
        return 0

    renamed = 0
    for mat in bpy.data.materials:
        tree = getattr(mat, "node_tree", None)
        if tree is None:
            continue
        for node in tree.nodes:
            if getattr(node, "bl_idname", "") != "ShaderNodeAttribute":
                continue
            if getattr(node, "attribute_name", "") == LEGACY_UV_TRANSFORM_ATTR:
                node.attribute_name = CANONICAL_UV_TRANSFORM_ATTR
                renamed += 1

    if renamed:
        logger.info("Migrated %d material UV-transform attribute node(s)", renamed)
    return renamed


def purge_all_obsolete_mesh_attributes() -> int:
    """Purges all dead, obsolete, and redundant MTK attributes from existing meshes in bpy.data.meshes."""
    try:
        import bpy
    except ImportError:
        return 0

    from .cleaner import clean_obsolete_mesh_attributes

    total_cleaned = 0
    for mesh in bpy.data.meshes:
        removed = clean_obsolete_mesh_attributes(mesh)
        if removed:
            total_cleaned += len(removed)

    if total_cleaned > 0:
        logger.info("Purged %d obsolete/dead mesh attribute(s) across meshes", total_cleaned)
    return total_cleaned


def run_all_migrations() -> None:
    """Runs material shader migrations and sweeps obsolete mesh attributes."""
    migrate_legacy_uv_attribute_names()
    purge_all_obsolete_mesh_attributes()


def register_migration_handlers() -> None:
    """Run migrations now and hook them onto ``load_post`` for opened files."""
    global _migration_handler
    if _migration_handler is not None:
        return

    import bpy

    run_all_migrations()

    @bpy.app.handlers.persistent
    def _mtk_migrate_on_load(_dummy: object) -> None:
        run_all_migrations()

    _migration_handler = _mtk_migrate_on_load
    if _migration_handler not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_migration_handler)


def unregister_migration_handlers() -> None:
    global _migration_handler
    if _migration_handler is None:
        return

    try:
        import bpy

        if _migration_handler in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(_migration_handler)
    except Exception:
        pass

    _migration_handler = None
