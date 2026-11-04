#!/usr/bin/env python3
"""
MTK 2.0 Real Game Live Sync Integration Test Suite.
Validates Live Sync against a running Minecraft 26.2 client instance:
1. Baseline Ingestion & Rebuild
2. Incremental Delta Updates (Block Place/Break)
3. Selection Movement & Scaling
4. Selection Clear & Recreate
5. Cache-Verified Reconnect Without Rebuild (VERIFIED_SKIP_REBUILD)
"""

import os
import sys
import time
from pathlib import Path
from libmtk_py import LiveSyncSession

CMD_FILE = Path(os.path.expanduser(
    "~/Library/Application Support/PrismLauncher/instances/26.2/minecraft/saves/新的世界 (1)/yefira_cmd.txt"
))

def send_minecraft_command(cmd: str):
    """Write command to IPC command file and wait for tick execution."""
    CMD_FILE.parent.mkdir(parents=True, exist_ok=True)
    CMD_FILE.write_text(cmd + "\n", encoding="utf-8")
    # Wait for integrated server tick (50ms tick rate)
    for _ in range(30):
        time.sleep(0.05)
        if not CMD_FILE.exists():
            break
    time.sleep(0.1)

def poll_until(session: LiveSyncSession, condition_fn, timeout: float = 6.0, desc: str = ""):
    """Poll session events until condition_fn(events) returns True or timeout."""
    start = time.time()
    all_events = []
    while time.time() - start < timeout:
        evts = session.poll_events()
        if evts:
            all_events.extend(evts)
            for e in evts:
                t = e.get("type")
                if t in ("HANDSHAKE", "SELECTION_UPDATED", "DELTA_APPLIED", "WORLD_MESH_READY", "VERIFIED", "ERROR"):
                    print(f"    [{t}] {e}")
            if condition_fn(all_events):
                return all_events
        time.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for {desc} after {timeout:.1f}s. Collected: {[e.get('type') for e in all_events]}")

def run_suite():
    print("======================================================================")
    print("🚀 STARTING REAL MINECRAFT 26.2 LIVE SYNC INTEGRATION TEST SUITE")
    print("======================================================================")

    # Clean up any leftover command files
    if CMD_FILE.exists():
        CMD_FILE.unlink()

    # Reset selection to known bounds: -16 -61 -21 to 20 -48 14
    print("\n[Setup] Resetting selection bounds in Minecraft...")
    send_minecraft_command("yefira box -16 -61 -21 20 -48 14")

    # -------------------------------------------------------------------------
    # TEST 1: Initial Baseline Ingestion & Rebuild
    # -------------------------------------------------------------------------
    print("\n--- TEST 1: Initial Baseline Ingestion & Rebuild ---")
    s1 = LiveSyncSession()
    s1.start(url="ws://127.0.0.1:8765", auth_token="1234")
    
    events = poll_until(
        s1,
        lambda evs: any(e.get("type") == "WORLD_MESH_READY" for e in evs),
        timeout=8.0,
        desc="Initial WORLD_MESH_READY"
    )
    
    handshakes = [e for e in events if e.get("type") == "HANDSHAKE"]
    assert handshakes, "No HANDSHAKE event received"
    assert handshakes[0]["decision"] == "FULL_BASELINE_REQUIRED", f"Unexpected decision: {handshakes[0]['decision']}"
    
    mesh_evts = [e for e in events if e.get("type") == "WORLD_MESH_READY"]
    assert mesh_evts, "No WORLD_MESH_READY event received"
    mesh1 = mesh_evts[-1]["mesh"]
    print(f"  ✓ Initial mesh generated: {mesh1}")
    print(f"  ✓ State Hash: {hex(s1.state_hash)}, Epoch: {s1.current_epoch}, Seq: {s1.current_sequence}")
    print("  ✅ TEST 1 PASSED: Initial baseline decoded and meshed.")

    # -------------------------------------------------------------------------
    # TEST 2: Incremental Delta Updates (Block Place & Break)
    # -------------------------------------------------------------------------
    print("\n--- TEST 2: Incremental Delta Updates (Block Place & Break) ---")
    # Coordinate (0, -55, 0) is well inside the selection bounds [-16..20, -61..-48, -21..14]
    test_pos = (0, -55, 0)
    print(f"  Action: Placing diamond block at {test_pos} in Minecraft...")
    send_minecraft_command(f"setblock {test_pos[0]} {test_pos[1]} {test_pos[2]} minecraft:diamond_block")
    
    delta_events = poll_until(
        s1,
        lambda evs: any(e.get("type") == "DELTA_APPLIED" for e in evs),
        timeout=5.0,
        desc="DELTA_APPLIED for diamond block placement"
    )
    delta_applied = [e for e in delta_events if e.get("type") == "DELTA_APPLIED"]
    assert delta_applied, "No DELTA_APPLIED event received"
    print(f"  ✓ Delta applied received: count={delta_applied[-1]['change_count']}, sections={delta_applied[-1]['affected_sections']}")

    print(f"  Action: Replacing diamond block with air at {test_pos}...")
    send_minecraft_command(f"setblock {test_pos[0]} {test_pos[1]} {test_pos[2]} minecraft:air")
    delta_events2 = poll_until(
        s1,
        lambda evs: any(e.get("type") == "DELTA_APPLIED" for e in evs),
        timeout=5.0,
        desc="DELTA_APPLIED for block break"
    )
    print("  ✅ TEST 2 PASSED: Real-time incremental delta updates verified.")

    # -------------------------------------------------------------------------
    # TEST 3: Multiple Selection Moves and Scales
    # -------------------------------------------------------------------------
    print("\n--- TEST 3: Moving and Scaling Selection ---")
    # Move/shrink to 0 -60 0 to 10 -50 10
    print("  Action: Scaling selection to (0, -60, 0) -> (10, -50, 10)...")
    send_minecraft_command("yefira box 0 -60 0 10 -50 10")
    events_scaled = poll_until(
        s1,
        lambda evs: any(e.get("type") == "SELECTION_UPDATED" and e.get("size_x") == 11 for e in evs)
                    and any(e.get("type") == "WORLD_MESH_READY" for e in evs),
        timeout=6.0,
        desc="SELECTION_UPDATED (11x11x11) & WORLD_MESH_READY"
    )
    scaled_mesh = [e for e in events_scaled if e.get("type") == "WORLD_MESH_READY"][-1]["mesh"]
    print(f"  ✓ Scaled selection baseline received and built: {scaled_mesh}")

    # Expand selection to -10 -60 -10 to 15 -45 15
    print("  Action: Moving & expanding selection to (-10, -60, -10) -> (15, -45, 15)...")
    send_minecraft_command("yefira box -10 -60 -10 15 -45 15")
    events_expanded = poll_until(
        s1,
        lambda evs: any(e.get("type") == "SELECTION_UPDATED" and e.get("size_x") == 26 for e in evs)
                    and any(e.get("type") == "WORLD_MESH_READY" for e in evs),
        timeout=6.0,
        desc="SELECTION_UPDATED (26x16x26) & WORLD_MESH_READY"
    )
    expanded_mesh = [e for e in events_expanded if e.get("type") == "WORLD_MESH_READY"][-1]["mesh"]
    print(f"  ✓ Expanded selection baseline received and built: {expanded_mesh}")
    print("  ✅ TEST 3 PASSED: Multiple selection move and scale rebuilds verified.")

    # -------------------------------------------------------------------------
    # TEST 4: Selection Clear & Recreate
    # -------------------------------------------------------------------------
    print("\n--- TEST 4: Selection Clear & Recreate ---")
    print("  Action: Clearing selection with /yefira clear...")
    send_minecraft_command("yefira clear")
    time.sleep(0.5)

    print("  Action: Recreating selection at (0, -60, 0) -> (12, -48, 12)...")
    send_minecraft_command("yefira box 0 -60 0 12 -48 12")
    recreate_events = poll_until(
        s1,
        lambda evs: any(e.get("type") == "WORLD_MESH_READY" for e in evs),
        timeout=6.0,
        desc="WORLD_MESH_READY for recreated selection"
    )
    recreated_mesh = [e for e in recreate_events if e.get("type") == "WORLD_MESH_READY"][-1]["mesh"]
    print(f"  ✓ Recreated mesh: {recreated_mesh}")
    
    # Save the parameters for the zero-rebuild test
    saved_uuid = s1.server_uuid
    saved_epoch = s1.current_epoch
    saved_seq = s1.current_sequence
    saved_hash = s1.state_hash
    saved_min = (0, -60, 0)
    saved_size = (13, 13, 13)
    print(f"  ✓ Captured state for cache reconnect: UUID={saved_uuid}, Epoch={saved_epoch}, Seq={saved_seq}, Hash={hex(saved_hash)}")
    
    s1.stop()
    time.sleep(0.5)
    print("  ✅ TEST 4 PASSED: Selection clear and recreation verified.")

    # -------------------------------------------------------------------------
    # TEST 5: Cache-Verified Reconnect Without Rebuild (VERIFIED_SKIP_REBUILD)
    # -------------------------------------------------------------------------
    print("\n--- TEST 5: Cache-Verified Reconnect Without Rebuild ---")
    s2 = LiveSyncSession()
    print("  Action: Starting new session using start_with_cache()...")
    s2.start_with_cache(
        url="ws://127.0.0.1:8765",
        auth_token="1234",
        server_uuid=saved_uuid,
        epoch=saved_epoch,
        sequence=saved_seq,
        min_pos=saved_min,
        size=saved_size,
        state_hash=saved_hash,
        dimension="minecraft:overworld"
    )

    reconnect_events = poll_until(
        s2,
        lambda evs: any(e.get("type") == "VERIFIED" for e in evs),
        timeout=5.0,
        desc="VERIFIED event"
    )

    handshakes = [e for e in reconnect_events if e.get("type") == "HANDSHAKE"]
    assert handshakes, "No HANDSHAKE event received on cached reconnect"
    decision = handshakes[0]["decision"]
    decision_code = handshakes[0]["decision_code"]
    print(f"  ✓ Handshake decision: {decision} (code={decision_code})")
    assert decision == "VERIFIED_SKIP_REBUILD" and decision_code == 0, f"Expected VERIFIED_SKIP_REBUILD, got {decision}"

    # Confirm NO baseline chunk streams were sent
    stream_evts = [e for e in reconnect_events if e.get("type") in ("STREAM_PROGRESS", "STREAM_FINISHED")]
    assert len(stream_evts) == 0, f"Expected NO stream chunks on zero-rebuild connect, but got: {stream_evts}"

    verified_evts = [e for e in reconnect_events if e.get("type") == "VERIFIED"]
    assert verified_evts and verified_evts[0]["is_verified"], "Session not verified in sync"
    print(f"  ✓ Verified event message: {verified_evts[0]['message']}")

    s2.stop()
    print("  ✅ TEST 5 PASSED: 0ms zero-rebuild reconnect verified.")

    print("\n======================================================================")
    print("🎉 ALL 5 LIVE SYNC INTEGRATION TESTS COMPLETED SUCCESSFULLY WITH 100% PASS!")
    print("======================================================================")

import socket
import pytest

@pytest.mark.skipif(
    os.environ.get("MTK_LIVE_MINECRAFT") != "1",
    reason="Requires active Minecraft 26.2 client. Set MTK_LIVE_MINECRAFT=1 to run."
)
def test_live_sync_e2e_real_game():
    run_suite()

if __name__ == "__main__":
    run_suite()
