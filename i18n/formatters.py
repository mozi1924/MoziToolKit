"""
MoziToolKit Dynamic Backend & Progress Message Formatting & Localization.

Provides regex-based pattern recognition and translation for dynamic strings
emitted from native Rust libmtk core (progress throttlers, live sync events,
worker milestone logs, and backend exceptions).
"""

from __future__ import annotations

import re
from typing import Optional

import bpy

from . import tr


def is_chinese_locale() -> bool:
    """Returns True if the current Blender locale is Chinese."""
    if hasattr(bpy, "context") and hasattr(bpy.context, "preferences"):
        view = getattr(bpy.context.preferences, "view", None)
        if view:
            use_tr = getattr(view, "use_translate_interface", True)
            if not use_tr:
                return False
            lang = getattr(view, "language", "")
            if lang and lang.startswith("zh"):
                return True
            if lang and not lang.startswith("zh") and lang != "DEFAULT":
                return False

    if hasattr(bpy, "app") and hasattr(bpy.app, "translations"):
        locale = getattr(bpy.app.translations, "locale", "")
        if locale:
            return locale.startswith("zh")

    # Direct fallback for mock / pytest headless test environments without real bpy
    return True


def format_progress_title(title: str) -> str:
    """
    Translates and formats progress bar titles (e.g. 'Import overworld',
    'Refreshing New World', 'Precompiling Assets').
    """
    if not title:
        return ""

    if not is_chinese_locale():
        return title

    direct = tr(title)
    if direct != title:
        return direct

    # Dynamic dimension imports: 'Import overworld' -> '导入主世界'
    m_import = re.match(r"^Import\s+([a-zA-Z0-9_]+)$", title, re.IGNORECASE)
    if m_import:
        dim = m_import.group(1).lower()
        dim_tr = tr(dim)
        if dim_tr != dim:
            return f"导入{dim_tr}"
        return f"导入 {m_import.group(1)}"

    # 'Refreshing <level_name>' -> '正在刷新 <level_name>'
    m_refresh = re.match(r"^Refreshing\s+(.*)$", title)
    if m_refresh:
        return f"正在刷新 {m_refresh.group(1)}"

    # 'Precompiling <pack_name>' -> '正在预编译 <pack_name>'
    m_precompile = re.match(r"^Precompiling\s+(.*)$", title)
    if m_precompile:
        return f"正在预编译 {m_precompile.group(1)}"

    # 'Rebuilding <target>' -> '正在重建 <target>'
    m_rebuild = re.match(r"^Rebuilding\s+(.*)$", title)
    if m_rebuild:
        target = m_rebuild.group(1)
        target_tr = tr(target)
        if target_tr != target:
            return f"正在重建{target_tr}"
        return f"正在重建 {target}"

    return title


def format_backend_message(msg: str) -> str:
    """
    Translates and normalizes messages emitted by Rust core or Live Sync.
    Handles static phrases, throttler (current/total) prefixes, stream events,
    and milestone statistics.
    """
    if not msg:
        return ""

    if not is_chinese_locale():
        return msg

    # 1. Exact static match in dictionary
    direct = tr(msg)
    if direct != msg:
        return direct

    # 2. Dynamic progress reports with counters
    # e.g. "Loaded 500 chunk sections from 100 chunks"
    m = re.match(r"^Loaded\s+(\d+)\s+chunk sections from\s+(\d+)\s+chunks$", msg)
    if m:
        return f"已从 {m.group(2)} 个区块加载 {m.group(1)} 个区块切片"

    # e.g. "Completed baking 1234 model variants"
    m = re.match(r"^Completed baking\s+(\d+)\s+model variants$", msg)
    if m:
        return f"已完成烘焙 {m.group(1)} 个模型变体"

    # e.g. "Assembled world mesh from 100 chunks"
    m = re.match(r"^Assembled world mesh from\s+(\d+)\s+chunks$", msg)
    if m:
        return f"已组装来自 {m.group(1)} 个区块的世界网格"

    # e.g. "Receiving chunk 5/10" or "Receiving chunk (5/10 ...)"
    m = re.match(r"^Receiving chunk\s+(\d+/\d+)$", msg)
    if m:
        return f"{tr('Receiving chunk')} ({m.group(1)})"
    m = re.match(r"^Receiving chunk\s+\((\d+/\d+)\s*(.*)\)$", msg)
    if m:
        sub = f" {m.group(2)}" if m.group(2) else ""
        return f"{tr('Receiving chunk')} ({m.group(1)}{sub})"

    # e.g. "Receiving Baseline stream (0/10)"
    m = re.match(r"^Receiving Baseline stream\s*\(0/(\d+)\)$", msg)
    if m:
        return f"{tr('Receiving Baseline stream')} (0/{m.group(1)})"

    # e.g. "Stream Complete (10 active chunks)" or "Stream Complete (10 chunks received)"
    m = re.match(r"^Stream Complete\s*\((\d+)\s+active chunks\)$", msg)
    if m:
        return f"{tr('Stream Complete')} ({m.group(1)} 个活跃区块)"
    m = re.match(r"^Stream Complete\s*\((\d+)\s+chunks received\)$", msg)
    if m:
        return f"{tr('Stream Complete')} (已接收 {m.group(1)} 个区块)"

    # e.g. "Mesh ready (1,234 v, 567 f)"
    m = re.match(r"^Mesh ready\s*\(([\d,]+)\s*v,\s*([\d,]+)\s*f\)$", msg)
    if m:
        return f"网格已就绪 ({m.group(1)} 顶点, {m.group(2)} 面)"

    # e.g. "World Mesh updated: 1,234 vertices, 567 faces"
    m = re.match(r"^World Mesh updated:\s*([\d,]+)\s*vertices,\s*([\d,]+)\s*faces$", msg)
    if m:
        return f"{tr('World Mesh updated')}: {m.group(1)} 顶点, {m.group(2)} 面"

    # e.g. "Rebuilt World Mesh: 1,234 vertices, 567 faces"
    m = re.match(r"^Rebuilt World Mesh:\s*([\d,]+)\s*vertices,\s*([\d,]+)\s*faces$", msg)
    if m:
        return f"{tr('Rebuilt World Mesh')}: {m.group(1)} 顶点, {m.group(2)} 面"

    # e.g. "World mesh rebuilt: 1,234 vertices, 567 faces"
    m = re.match(r"^World mesh rebuilt(.*):\s*([\d,]+)\s*vertices,\s*([\d,]+)\s*faces$", msg)
    if m:
        return f"世界网格已重建{m.group(1)}: {m.group(2)} 顶点, {m.group(3)} 面"

    # e.g. "Live Sync mesh rebuilt: 1,234 vertices, 567 faces"
    m = re.match(r"^Live Sync mesh rebuilt:\s*([\d,]+)\s*vertices,\s*([\d,]+)\s*faces$", msg)
    if m:
        return f"实时同步网格已重建: {m.group(1)} 顶点, {m.group(2)} 面"

    # e.g. "Detected 3 out-of-sync sections"
    m = re.match(r"^Detected\s+(\d+)\s+out-of-sync sections?.*$", msg)
    if m:
        return f"检测到 {m.group(1)} 个未同步的区块切片"

    # e.g. "Out of sync: <msg>"
    m = re.match(r"^Out of sync:\s*(.*)$", msg)
    if m:
        return f"未同步: {format_backend_message(m.group(1))}"

    # e.g. "Sync Handshake: 10 chunks (1,000 blocks)"
    m = re.match(r"^Sync Handshake:\s*(\d+)\s+chunks\s*\(([\d,]+)\s+blocks\)$", msg)
    if m:
        return f"同步握手: {m.group(1)} 个区块 ({m.group(2)} 个方块)"

    # e.g. "Delta Applied: 5 block modification(s)"
    m = re.match(r"^Delta Applied:\s*(\d+)\s+block modification\(s\)$", msg)
    if m:
        return f"增量应用: {m.group(1)} 个方块变动"

    # e.g. "Connecting to ws://127.0.0.1:25565/sync..."
    m = re.match(r"^Connecting to\s+(.*?)\.\.\.$", msg)
    if m:
        return f"正在连接至 {m.group(1)}..."

    # e.g. "Connecting Live Sync for 'World' at ws://..."
    m = re.match(r"^Connecting Live Sync for '(.*?)' at (.*?)$", msg)
    if m:
        return f"正在为 '{m.group(1)}' 连接实时同步 ({m.group(2)})"

    # 3. Live Sync Watchdog, Resync, and Warning Messages
    # e.g. "Baseline validation failed (SequenceGap); requesting a fresh snapshot..."
    m = re.match(r"^Baseline validation failed\s*\((.*?)\);\s*requesting a fresh snapshot\.\.\.$", msg)
    if m:
        return f"基线校验失败 ({m.group(1)})，正在请求新快照..."

    # e.g. "Baseline validation failed 3 times for this selection; click Refresh or change the Minecraft selection to retry."
    m = re.match(r"^Baseline validation failed\s+(\d+)\s+times for this selection;\s*click Refresh or change the Minecraft selection to retry\.$", msg)
    if m:
        return f"当前选区基线校验已连续失败 {m.group(1)} 次；请点击刷新或修改 Minecraft 选区重试。"

    # e.g. "Server cancelled the baseline stream (ResourceLimitExceeded); waiting for the next snapshot..."
    m = re.match(r"^Server cancelled the baseline stream\s*\((.*?)\);\s*waiting for the next snapshot\.\.\.$", msg)
    if m:
        return f"服务端已取消基线数据流 ({m.group(1)})，等待下一个快照..."

    # e.g. "Connection rejected by server: <detail>"
    m = re.match(r"^Connection rejected by server:\s*(.*)$", msg)
    if m:
        return f"连接已被服务端拒绝: {m.group(1)}"

    # e.g. "Selection volume 123456 exceeds the 65536 voxel protocol limit; shrink the selection and reconnect."
    m = re.match(r"^Selection volume\s+(\d+)\s+exceeds the\s+(\d+)\s+voxel protocol limit;\s*shrink the selection and reconnect\.$", msg)
    if m:
        return f"选区体积 {m.group(1)} 超出协议限制 ({m.group(2)} 体素)；请缩小选区后重新连接。"

    # e.g. "Packet decode error: <detail>"
    m = re.match(r"^Packet decode error:\s*(.*)$", msg)
    if m:
        return f"数据包解码错误: {m.group(1)}"

    # 4. ProgressThrottler prefix matching (e.g. "Loading chunk (5/20)" or "load_chunks: (5/20)")
    # Case A: prefix with colon: "load_chunks: (5/20)"
    m = re.match(r"^([a-zA-Z0-9_]+):\s*(\(\d+/\d+.*?\))$", msg)
    if m:
        stage = m.group(1)
        trans_stage = tr(stage)
        if trans_stage != stage:
            return f"{trans_stage} {m.group(2)}"

    # Case B: prefix with parenthesis: "Loading chunk (5/20)" or "Meshing chunk (5/20)"
    if "(" in msg:
        prefix, rest = msg.split("(", 1)
        clean_prefix = prefix.strip()
        trans_prefix = tr(clean_prefix)
        if trans_prefix != clean_prefix:
            return f"{trans_prefix} ({rest}"

    return msg


def format_backend_error(error_msg: str) -> str:
    """
    Translates common exceptions or error messages originating from the Rust backend.
    """
    if not error_msg:
        return ""

    if not is_chinese_locale():
        return error_msg

    # "Unsupported or legacy Minecraft DataVersion (1343); minimum supported is 2844 (1.18+)"
    m = re.match(r"^Unsupported or legacy Minecraft DataVersion \((\d+)\); minimum supported is 2844 \(1\.18\+\)$", error_msg)
    if m:
        return f"不支持或过旧的 Minecraft 数据版本 ({m.group(1)})；最低支持版本为 2844 (1.18+)"

    # "level.dat not found at: <path>"
    m = re.match(r"^level\.dat not found at:\s*(.*)$", error_msg)
    if m:
        return f"未在以下路径找到 level.dat: {m.group(1)}"

    # "Region directory not found at: <path>"
    m = re.match(r"^Region directory not found at:\s*(.*)$", error_msg)
    if m:
        return f"未在以下路径找到 Region 区域文件夹: {m.group(1)}"

    # "Missing vanilla base pack: <detail>"
    m = re.match(r"^Missing vanilla base pack:\s*(.*)$", error_msg)
    if m:
        return f"缺失原版基础资源包: {m.group(1)}"

    # "Missing assets: <detail>"
    m = re.match(r"^Missing assets:\s*(.*)$", error_msg)
    if m:
        return f"缺失资源资产: {m.group(1)}"

    # "Thread pool error: <detail>"
    m = re.match(r"^Thread pool error:\s*(.*)$", error_msg)
    if m:
        return f"线程池错误: {m.group(1)}"

    # "Coordinate out of bounds: (x, y, z)"
    m = re.match(r"^Coordinate out of bounds:\s*(\(.*?\))$", error_msg)
    if m:
        return f"坐标超出边界: {m.group(1)}"

    # "Chunk decompression failed: <detail>"
    m = re.match(r"^Chunk decompression failed:\s*(.*)$", error_msg)
    if m:
        return f"区块解压失败: {m.group(1)}"

    # "Corrupt or invalid chunk data: <detail>"
    m = re.match(r"^Corrupt or invalid chunk data:\s*(.*)$", error_msg)
    if m:
        return f"损坏或无效的区块数据: {m.group(1)}"

    # "Invalid region file header: <detail>"
    m = re.match(r"^Invalid region file header:\s*(.*)$", error_msg)
    if m:
        return f"无效的 Region 文件头: {m.group(1)}"

    # "Unsupported chunk compression type: <detail>"
    m = re.match(r"^Unsupported chunk compression type:\s*(.*)$", error_msg)
    if m:
        return f"不支持的区块压缩类型: {m.group(1)}"

    # "World lock poisoned: <detail>"
    m = re.match(r"^World lock poisoned:\s*(.*)$", error_msg)
    if m:
        return f"世界锁中毒异常: {m.group(1)}"

    return error_msg
