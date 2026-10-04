"""
Unit tests for the Unified Engine Bridge (bridge/engine.py).
Validates dynamic loading, graceful fallbacks, and bridge encapsulation across all modules.
"""

import pytest


class TestEngineBridge:
    def test_engine_resolution_and_info(self):
        from MoziToolKit.bridge.engine import get_libmtk, has_libmtk, require_libmtk, get_engine_info

        assert has_libmtk() is True
        mtk = get_libmtk()
        assert mtk is not None
        assert require_libmtk() is mtk

        info = get_engine_info()
        assert info["available"] is True
        assert "mode" in info
        assert "path" in info
        assert "version" in info

    def test_dynamic_attributes_on_bridges(self):
        """Verifies PEP 562 dynamic attributes resolve correctly without static freeze."""
        from MoziToolKit.bridge import material, mesh, uv, subdivide, cull, extrude

        # Dynamic classes in material bridge
        assert hasattr(material, "BiomeResolver")
        assert material.BiomeResolver is not None
        assert hasattr(material, "MaterialResolver")
        assert hasattr(material, "GridAtlasSpec")
        assert material.HAS_LIBMTK is True

        # Dynamic classes in mesh bridge
        assert hasattr(mesh, "MeshData")
        assert hasattr(mesh, "AttributeDomain")
        assert hasattr(mesh, "mtk_py")

        # Dynamic mtk_py references in other bridges
        assert hasattr(uv, "mtk_py")
        assert hasattr(subdivide, "mtk_py")
        assert hasattr(cull, "mtk_py")
        assert hasattr(extrude, "mtk_py")

    def test_system_dependencies_has_libmtk(self):
        """Verifies utils.system.dependencies routes through bridge.engine."""
        from MoziToolKit.utils.system.dependencies import has_libmtk

        assert has_libmtk() is True
