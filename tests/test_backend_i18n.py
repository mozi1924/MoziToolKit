"""
Tests for backend and progress message localization & formatting (i18n).
Verifies that all dynamic milestone messages, throttler prefixes, sync events,
and error messages from the Rust backend (libmtk / mtk-sync / mtk-save / mtk-voxel)
are properly translated and formatted for display in Blender status bar and UI panels.
"""

import unittest
from types import SimpleNamespace

import bpy

from MoziToolKit.i18n import (
    format_backend_error,
    format_backend_message,
    format_progress_title,
    is_chinese_locale,
    tr,
)
from MoziToolKit.utils.progress import BlenderProgressReporter


class TestBackendI18n(unittest.TestCase):
    saved_lang = None
    saved_ui = False

    @classmethod
    def setUpClass(cls):
        """Ensures i18n is registered and active in Chinese during test execution."""
        try:
            import MoziToolKit.i18n as i18n
            i18n.register()
        except Exception:
            pass
        view = getattr(bpy.context.preferences, "view", None)
        if view:
            cls.saved_lang = getattr(view, "language", "DEFAULT")
            cls.saved_ui = getattr(view, "use_translate_interface", False)
            view.language = "zh_HANS"
            view.use_translate_interface = True

    @classmethod
    def tearDownClass(cls):
        """Restores original language preferences."""
        if cls.saved_lang is not None:
            view = getattr(bpy.context.preferences, "view", None)
            if view:
                view.language = cls.saved_lang
                view.use_translate_interface = cls.saved_ui

    def test_static_dictionary_entries(self):
        """Verifies that all static Rust progress and sync tokens exist in dictionary."""
        self.assertEqual(tr("Loading chunk"), "加载区块切片")
        self.assertEqual(tr("Meshing chunk"), "生成区块网格")
        self.assertEqual(tr("Baking block models"), "烘焙方块模型")
        self.assertEqual(tr("Packaging atlas chunk textures"), "打包图集分块贴图")
        self.assertEqual(tr("Resolving player head skins"), "加载玩家头颅皮肤")
        self.assertEqual(tr("Extracting biome mappings and colormaps..."), "正在提取生物群系映射与调色板...")
        self.assertEqual(tr("Extracted biome mappings and colormaps"), "已提取生物群系映射与调色板")
        self.assertEqual(tr("Packing sprite textures into atlases..."), "正在将纹理精灵打包至图集...")
        self.assertEqual(tr("Saved .mtkcache binary package and completed precompilation"), "已保存 .mtkcache 二进制缓存包并完成预编译")
        self.assertEqual(tr("Indexing model definitions..."), "正在索引方块模型定义...")
        self.assertEqual(tr("No sections to mesh"), "没有可生成网格的区块切片")

        # Sync lifecycle tokens
        self.assertEqual(tr("AWAITING_BASELINE"), "等待基线数据")
        self.assertEqual(tr("RECEIVING_BASELINE"), "正在接收基线数据")
        self.assertEqual(tr("VALIDATING_HASH"), "正在校验哈希")
        self.assertEqual(tr("REPLAYING_STAGED"), "正在重放暂存增量")
        self.assertEqual(tr("BUILDING_MESH"), "正在构建网格")
        self.assertEqual(tr("LIVE"), "实时同步中")

        # Sync stage titles
        self.assertEqual(tr("Live Sync: Download"), "实时同步: 下载数据")
        self.assertEqual(tr("Live Sync: Mesh"), "实时同步: 构建网格")
        self.assertEqual(tr("Live Sync: Request"), "实时同步: 请求快照")

    def test_throttler_dynamic_messages(self):
        """Verifies throttler messages generated with .with_prefix() or stage fallbacks."""
        # Save loading chunk throttler
        msg1 = format_backend_message("Loading chunk (15/100)")
        self.assertEqual(msg1, "加载区块切片 (15/100)")

        # Section mesher throttler
        msg2 = format_backend_message("Meshing chunk (4/16)")
        self.assertEqual(msg2, "生成区块网格 (4/16)")

        # Prebake model baking throttler
        msg3 = format_backend_message("Baking block models (250/500)")
        self.assertEqual(msg3, "烘焙方块模型 (250/500)")

        # Atlas packaging throttler
        msg4 = format_backend_message("Packaging atlas chunk textures (1/3)")
        self.assertEqual(msg4, "打包图集分块贴图 (1/3)")

        # Head skin resolving throttler
        msg5 = format_backend_message("Resolving player head skins (3/10)")
        self.assertEqual(msg5, "加载玩家头颅皮肤 (3/10)")

        # Default fallback stage format without prefix
        msg6 = format_backend_message("load_chunks: (10/50)")
        self.assertEqual(msg6, "加载区块 (10/50)")

        msg7 = format_backend_message("meshing_sections: (2/8)")
        self.assertEqual(msg7, "网格化区块切片 (2/8)")

    def test_milestone_completion_messages(self):
        """Verifies final milestone / summary messages with dynamic counts."""
        # Save loaded sections
        m1 = format_backend_message("Loaded 450 chunk sections from 64 chunks")
        self.assertEqual(m1, "已从 64 个区块加载 450 个区块切片")

        # Models prebaked
        m2 = format_backend_message("Completed baking 1280 model variants")
        self.assertEqual(m2, "已完成烘焙 1280 个模型变体")

        # World mesh assembled
        m3 = format_backend_message("Assembled world mesh from 64 chunks")
        self.assertEqual(m3, "已组装来自 64 个区块的世界网格")

        # Sync stream chunks
        m4 = format_backend_message("Receiving chunk 5/20")
        self.assertEqual(m4, "正在接收区块切片 (5/20)")

        m5 = format_backend_message("Receiving Baseline stream (0/32)")
        self.assertEqual(m5, "正在接收基线数据流 (0/32)")

        # Stream finished
        m6 = format_backend_message("Stream Complete (64 active chunks)")
        self.assertEqual(m6, "数据流传输完毕 (64 个活跃区块)")

        # Mesh ready stats
        m7 = format_backend_message("Mesh ready (12,345 v, 6,789 f)")
        self.assertEqual(m7, "网格已就绪 (12,345 顶点, 6,789 面)")

        # World mesh updated
        m8 = format_backend_message("World Mesh updated: 10,000 vertices, 5,000 faces")
        self.assertEqual(m8, "世界网格已更新: 10,000 顶点, 5,000 面")

    def test_live_sync_watchdog_and_warnings(self):
        """Verifies Live Sync status, watchdog, and server error messages."""
        w1 = format_backend_message("Waiting for Baseline stream...")
        self.assertEqual(w1, "等待基线数据流...")

        w2 = format_backend_message("100% in sync with scene (Zero-Rebuild verified)")
        self.assertEqual(w2, "与场景完全同步 (零重建校验通过)")

        w3 = format_backend_message("Baseline stream stalled; requesting a fresh snapshot...")
        self.assertEqual(w3, "基线数据流停滞，正在请求新快照...")

        w4 = format_backend_message("Baseline validation failed (SequenceGap); requesting a fresh snapshot...")
        self.assertEqual(w4, "基线校验失败 (SequenceGap)，正在请求新快照...")

        w5 = format_backend_message("Baseline validation failed 3 times for this selection; click Refresh or change the Minecraft selection to retry.")
        self.assertEqual(w5, "当前选区基线校验已连续失败 3 次；请点击刷新或修改 Minecraft 选区重试。")

        w6 = format_backend_message("Server cancelled the baseline stream (ResourceLimitExceeded); waiting for the next snapshot...")
        self.assertEqual(w6, "服务端已取消基线数据流 (ResourceLimitExceeded)，等待下一个快照...")

        w7 = format_backend_message("Connection rejected by server: Authentication failed")
        self.assertEqual(w7, "连接已被服务端拒绝: Authentication failed")

        w8 = format_backend_message("Selection volume 100000 exceeds the 65536 voxel protocol limit; shrink the selection and reconnect.")
        self.assertEqual(w8, "选区体积 100000 超出协议限制 (65536 体素)；请缩小选区后重新连接。")

        w9 = format_backend_message("Packet decode error: unexpected EOF")
        self.assertEqual(w9, "数据包解码错误: unexpected EOF")

    def test_progress_title_formatting(self):
        """Verifies dynamic progress title translation."""
        self.assertEqual(format_progress_title("Import overworld"), "导入主世界")
        self.assertEqual(format_progress_title("Import the_nether"), "导入下界")
        self.assertEqual(format_progress_title("Import the_end"), "导入末地")
        self.assertEqual(format_progress_title("Refreshing MyWorld"), "正在刷新 MyWorld")
        self.assertEqual(format_progress_title("Precompiling Faithful_32x.zip"), "正在预编译 Faithful_32x.zip")
        self.assertEqual(format_progress_title("Rebuilding World Mesh"), "正在重建世界网格")

    def test_backend_error_formatting(self):
        """Verifies formatting of native exceptions."""
        e1 = format_backend_error("Unsupported or legacy Minecraft DataVersion (1343); minimum supported is 2844 (1.18+)")
        self.assertEqual(e1, "不支持或过旧的 Minecraft 数据版本 (1343)；最低支持版本为 2844 (1.18+)")

        e2 = format_backend_error("level.dat not found at: /path/to/world/level.dat")
        self.assertEqual(e2, "未在以下路径找到 level.dat: /path/to/world/level.dat")

        e3 = format_backend_error("Region directory not found at: /path/to/region")
        self.assertEqual(e3, "未在以下路径找到 Region 区域文件夹: /path/to/region")

        e4 = format_backend_error("Coordinate out of bounds: (100, 200, 300)")
        self.assertEqual(e4, "坐标超出边界: (100, 200, 300)")

    def test_blender_progress_reporter_status_text(self):
        """Verifies that BlenderProgressReporter formats status bar without redundant ratio strings."""
        ws = SimpleNamespace(status=None)
        ws.status_text_set = lambda text: setattr(ws, "status", text)
        wm = SimpleNamespace(
            progress_begin=lambda *a: None,
            progress_update=lambda *a: None,
            progress_end=lambda *a: None,
        )
        ctx = SimpleNamespace(window_manager=wm, workspace=ws)

        reporter = BlenderProgressReporter(context=ctx, total=100, title="Import overworld")
        reporter.start()

        # Update with throttler message containing ratio
        reporter.update(current=25, total=100, message="Loading chunk (25/100)")
        self.assertEqual(ws.status, "导入主世界: 加载区块切片 (25/100) (25%)")

        # Update with simple text without ratio
        reporter.update(current=50, total=100, message="Extracting biome mappings and colormaps...")
        self.assertEqual(ws.status, "导入主世界: 正在提取生物群系映射与调色板... (50/100, 50%)")

        reporter.close()

    def test_english_locale_preservation(self):
        """Verifies that when running under an English locale, original English strings are preserved."""
        view = getattr(bpy.context.preferences, "view", None)
        if not view:
            return

        # Temporarily switch to English
        view.language = "en_US"
        view.use_translate_interface = True
        try:
            self.assertFalse(is_chinese_locale())
            # In English, progress title and backend messages must remain in English
            self.assertEqual(format_progress_title("Import overworld"), "Import overworld")
            self.assertEqual(format_backend_message("Loading chunk (15/100)"), "Loading chunk (15/100)")
            self.assertEqual(format_backend_message("Waiting for Baseline stream..."), "Waiting for Baseline stream...")
            self.assertEqual(format_backend_error("Coordinate out of bounds: (1, 2, 3)"), "Coordinate out of bounds: (1, 2, 3)")
        finally:
            view.language = "zh_HANS"
            view.use_translate_interface = True


if __name__ == "__main__":
    unittest.main()
