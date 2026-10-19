"""
Tests for the shared FaceCuller cache used by the voxel world pipeline.

The Rust ``FaceCuller`` owns a blockstate-keyed metadata cache; rebuilding it on every
mesh call forced cull metadata to be re-derived for every unique block state. These
tests pin the reuse contract (same instance across calls, explicit reset).
"""

from __future__ import annotations


def test_shared_face_culler_is_reused():
    from MoziToolKit.bridge.engine import get_libmtk
    from MoziToolKit.bridge.world import get_shared_face_culler, reset_shared_face_culler

    mtk = get_libmtk()
    if mtk is None or not hasattr(mtk, "FaceCuller"):
        import pytest

        pytest.skip("native FaceCuller unavailable")

    reset_shared_face_culler()
    first = get_shared_face_culler()
    second = get_shared_face_culler()
    assert first is not None
    assert first is second

    reset_shared_face_culler()
    third = get_shared_face_culler()
    assert third is not None
    assert third is not first


def test_shared_culler_warms_across_mesh_calls():
    """A second rebuild with the shared culler must not be slower and must keep output stable."""
    from MoziToolKit.bridge.world import (
        get_shared_face_culler,
        mesh_voxel_storage,
        reset_shared_face_culler,
    )
    from MoziToolKit.bridge.engine import get_libmtk

    mtk = get_libmtk()
    if mtk is None or not hasattr(getattr(mtk, "VoxelStorage", None), "create_debug_world"):
        import pytest

        pytest.skip("native debug world unavailable")

    reset_shared_face_culler()
    storage = mtk.VoxelStorage.create_debug_world()

    first, _ = mesh_voxel_storage(
        storage=storage, resolve_prefs=False, resolve_ctm=False, atlas=False
    )
    assert get_shared_face_culler() is not None
    assert first.quad_count > 0

    second, _ = mesh_voxel_storage(
        storage=storage, resolve_prefs=False, resolve_ctm=False, atlas=False
    )
    assert second.quad_count == first.quad_count
    assert second.vertex_count == first.vertex_count
