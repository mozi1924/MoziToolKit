# RFC v3.1: MTK 2.0 Live Sync 协议与架构设计规范 (Binary Protocol v3.1)

> **文档状态**：Accepted / Implemented（已与 v2.0 实际代码及 Live Sync 稳定性修复对齐）
> **权威范围**：Yefira (Minecraft Java Mod) ↔ `mtk-sync` (Rust 核心) ↔ MoziToolKit (Blender/Python 前端)
> **适用版本**：MoziToolKit / libmozitoolkit / Yefira 2.0+
> **实现事实源**：
> - Rust：[`crates/mtk-sync`](../../../libmozitoolkit/crates/mtk-sync)
> - Java：[`common-core/.../network/WebSocketServerManager.java`](../../../yefira/common-core/src/main/java/com/mozi1924/yefira/network/WebSocketServerManager.java)
> - Python/Blender：[`bridge/sync.py`](../../bridge/sync.py)、[`operators/sync/`](../../operators/sync)
>
> 本文档是三端共同遵守的**协议与工程实现唯一事实源 (SSOT)**。任何一端的行为与本文冲突时，视为实现缺陷；当前代码与 RFC 初稿存在的刻意差异统一记录在 [§7 实现对齐矩阵与已知偏差](#7-实现对齐矩阵与已知偏差-implementation-matrix--deviations)。

---

## 0. 文档定位与不变量 (Document Contract & Invariants)

以下 8 条是 Live Sync 2.0 不可违背的硬不变量，任何优化/重构都不得破坏：

1. **单连接单快照流**：任一客户端任一时刻最多只有一条有效 Baseline 流。新选区/刷新/重同步必须通过代际 (generation) 使旧流失效。
2. **增量序号严格单调**：`sequence` 只增不减；客户端仅接受 `expected = current + 1` 的 `DELTA_OP`，缺口必须触发恢复。
3. **快照栅栏 (Snapshot Barrier)**：`BASELINE_BEGIN.snapshot_seq = S` 之后，所有 `seq > S` 的增量必须在快照安装后按序重放，`seq <= S` 的增量必须丢弃。
4. **调色板-增量一致性**：`DELTA_OP.state_id` 必须使用客户端当前 `palette_revision` 的调色板解析；基线扫描/推流期间不得用旧调色板编码新序号增量。
5. **状态指纹权威性**：只有 `state_hash` 完全一致才允许 `VERIFIED_SKIP_REBUILD`；任何方块变更、选区变更、服务端重启或维度变化都必须使缓存指纹失效。
6. **资源硬限优先**：`MaxSelectionVolume = 33,554,432` 体素；超限必须在扫描/分配前拒绝，不得先分配再失败。
7. **连接状态唯一权威**：宿主 UI 的连接状态必须来自原生会话的 `is_connected/status`，不得由单条中间态字符串推断。
8. **可恢复性**：任何半截基线、序号缺口、工作线程异常都必须收敛到“等待新基线或明确报错”，禁止永久卡在中间进度。

---

## 1. 架构分层与职责边界 (3-Layer Architecture)

```
+-----------------------------------------------------------------------------------+
| 3. 数据与应用层 (Data & Application Layer)                                         |
|    - Minecraft 端：Level 体素与生物群系提取、不可变快照生成                        |
|    - Rust 核心：VoxelStorage 连续体素容器、Rayon 并行网格化、mtk-model 烘焙、Atlas UV|
|    - Blender 端：DNA 裸指针零拷贝写入 (foreach_set 回退)、材质槽同步、场景持久化   |
+-----------------------------------------------------------------------------------+
                                         │  (纯内存数据结构 / MeshData)
+-----------------------------------------------------------------------------------+
| 2. 同步状态机与会话层 (Sync Session & State Machine Layer)                          |
|    - 显式握手协商 (HELLO / WELCOME)、SyncDecision 完整判定矩阵                     |
|    - 强代数与快照序号隔离 (Server Epoch, Client Generation, Snapshot Sequence)     |
|    - 快照与增量衔接缓冲队列 (Snapshot-Delta Staging & Replay)                      |
|    - 序号缺口检测、RESYNC_REQUEST、重同步限流与失败熔断                            |
|    - 全局规范化状态指纹 (Canonical state_hash) 与事务生命周期控制                  |
+-----------------------------------------------------------------------------------+
                                         │  (MTK Packets / Typed Events)
+-----------------------------------------------------------------------------------+
| 1. 传输与通道层 (Framing & Transport Layer)                                       |
|    - WebSocket 消息封装 (1 WebSocket Binary Message == 1 MTK Packet)               |
|    - 小端序 (Little-Endian) 编解码、变长字符串严格 UTF-8 校验与定长包头对齐         |
|    - 资源边界与尺寸硬限 (Resource Limits & Decompressed Size Guards)                |
|    - WebSocket 层保活心跳 (Ping/Pong) 与底层断线重连状态机                          |
+-----------------------------------------------------------------------------------+
```

### 1.1 代码模块导航 (Code Map)

| 层 | 端 | 入口文件 | 职责 |
| :--- | :--- | :--- | :--- |
| 协议编解码 | Rust | `crates/mtk-sync/src/protocol/codec.rs` | 定长帧头、LE 编解码、xxHash64 分块校验、资源上限 |
| 协议常量 | Rust | `crates/mtk-sync/src/protocol/constants.rs` | Opcode、SyncDecision、硬限、Cancel/Resync/Error 码 |
| 状态指纹 | Rust | `crates/mtk-sync/src/protocol/hasher.rs` | Canonical `state_hash` 计算 |
| 会话状态机 | Rust | `crates/mtk-sync/src/session/dispatcher.rs` | 握手、基线组装、Staging/Replay、看门狗、失败熔断 |
| 基线组装 | Rust | `crates/mtk-sync/src/session/assembler.rs` | 分块校验、体素/群系解包、SectionStorage 重建、指纹校验 |
| 增量暂存 | Rust | `crates/mtk-sync/src/session/staging.rs` | 快照期间增量排队与栅栏对齐 |
| 网络传输 | Rust | `crates/mtk-sync/src/client.rs` | 原生 WebSocket 客户端、重连、命令通道 |
| 协议编码 | Java | `encoder/BlockDataEncoder.java` | 服务端包编码、Canonical BlockState/Biome 序列化、ERROR |
| 规范扫描 | Java | `encoder/CanonicalVoxelScanner.java` | 选区连续扫描、xxHash64、协作取消 |
| 基线与增量 | Java | `network/WebSocketServerManager.java` | 单流代际、调色板、Delta 批处理、快速重连判定 |
| 前端桥接 | Python | `bridge/sync.py` | 原生会话单例、事件轮询、连接状态权威同步 |
| Blender 操作符 | Python | `operators/sync/op_sync_connect.py` | 连接/刷新/断开、网格注入、持久化、UI 状态 |
| 场景持久化 | Python | `operators/sync/hierarchy.py` | 根容器/子网格层级、`mtk_sync_*` 属性读写 |

---

## 2. 帧头规范、资源硬限与超时 (Framing, Limits & Timeouts)

### 2.1 4 字节标准帧头

所有数据包均以小端序 (Little-Endian) 编码，严格遵循 **1 个 WebSocket Binary Message 对应 1 个 MTK 数据包**（若底层传输分片，必须由 WebSocket 协议层组装为完整 Message 后再交付 MTK 解码器）：

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|          Magic 'M' 'T'        |  Ver (0x03)   |    Opcode     |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

* **Magic**：`0x4D, 0x54` (`'M', 'T'`)。非 `MT` 魔数 → 丢弃并断开连接，不分配缓冲。
* **Version**：`0x03`。主版本不兼容 → `ERROR(UNSUPPORTED_VERSION)` 后断开。
* **Opcode**：`0x01 ~ 0xFF`。未知 Opcode → `ERROR(UNKNOWN_OPCODE)` 并断开。

### 2.2 资源硬限与安全预检

| 参数项 | 目标硬限 | 当前实现 | 违规防御 |
| :--- | :--- | :--- | :--- |
| **MaxMessageSize（单包）** | 256 KiB（允许 512 KiB） | `mtk-sync::MAX_MESSAGE_SIZE = 512 KiB`；服务端 chunk payload 固定 `256 KiB`（整帧约 256 KiB + 64 B 头） | Rust 解码器拒绝超限；服务端按 256 KiB 切片 |
| **MaxPaletteStringBytes** | 1,024 B / 字符串 | 常量已定义；实际由服务端规范化字符串长度天然约束 | 非法 UTF-8 → `ERROR(INVALID_PALETTE)` |
| **MaxPaletteEntries** | 65,535 | `codec.rs` 对 BaselineBegin 严格校验 | 超限拒绝 Baseline |
| **TotalPaletteStringBytes** | 4 MiB | 常量已定义（当前未单独累计校验） | 由单串上限 + 条目上限间接约束 |
| **MaxBaselineEncodedBytes** | 64 MiB | 常量已定义 | 单包 ≤512 KiB + 分块总数受选区体积约束 |
| **MaxBaselineDecodedBytes** | 256 MiB | `codec.rs` 校验 `total_decoded_bytes` | 拒绝解压炸弹 |
| **MaxSelectionVolume** | 33,554,432 体素 | Rust 组装器 + Java `MAX_SELECTION_VOLUME` 双重校验 | 服务端在扫描前直接 `ERROR(0x0005)`；客户端拒绝并取消 |
| **MaxDeltaBatchChanges** | 16,384 / 批次 | Java `broadcastDeltaUpdate` 按 16,384 自动切批 | 每批独立单调 `sequence` |
| **MaxDeltaStagingBatches** | 256 批次 / 16 MiB | `staging.rs` 双重上限 | 溢出 → 中止基线并发起 `RESYNC_REQUEST` |
| **MaxPendingDeltaChanges** | — | Java 延迟队列上限 `262,144`（基线期间累积） | 溢出 → 转为重新广播全量 Baseline |

### 2.3 超时与生命周期矩阵

> 初稿中的目标值与当前实现存在差异。下表同时给出**目标值**与**当前代码行为**，以实现为准。

| 项目 | RFC 目标值 | 当前实现 | 状态 |
| :--- | :--- | :--- | :--- |
| **Handshake Timeout** | 连接后 5s 未完成 HELLO/WELCOME 则关闭 | 未实现服务端强制超时；客户端重连上限 5 次，UI 显示 `CONNECTING/RECONNECTING` | 📋 待实现 |
| **Baseline Idle Timeout** | 连续 10s 未收到下一 CHUNK 判定失败 | 客户端看门狗：`RECEIVING_BASELINE` 20s 无进展、`VALIDATING_HASH/REPLAYING_STAGED` 10s 无进展 → 丢弃基线并重同步 | ✅（数值不同） |
| **Baseline ACK Timeout** | 发完 END 后 15s 未收到 ACK 取消事务 | 服务端仅解析并记录 ACK 结果码，不强制超时 | 📋 待实现 |
| **Delta Gap Recovery** | `RESYNC_REQUEST` 后 3s 未补发则升级全量 | 重同步请求 900ms 限流；连续 3 次校验失败后暂停自动重试，等待手动 Refresh 或新选区 | ⚠️ 简化实现 |
| **Keepalive Ping** | 空闲每 20s 发送应用层 PING，45s 无 PONG 判定掉线 | 依赖 WebSocket 协议层 Ping/Pong（Java-WebSocket / tungstenite）；应用层 `0x0E/0x0F` 可用但未定时调度 | ⚠️ 依赖传输层 |
| **Resync 熔断** | — | 同一选区连续 3 次基线校验失败 → 停止自动重同步并显式报错 | ✅ 稳定性增强 |

---

## 3. 全局规范化状态指纹 (`state_hash`) 形式化规范

`state_hash` 是协议层世界状态的权威唯一事实源（SSOT）。它完全独立于网络切片大小、压缩算法与局部调色板顺序。

### 3.1 规范化约束与预处理

1. **坐标系与半开区间**：
   选区长方体严格采用半开区间 `[min_x, max_x)`, `[min_y, max_y)`, `[min_z, max_z)`。
   尺寸定义：`W = max_x - min_x`、`H = max_y - min_y`、`D = max_z - min_z`。

2. **三维内存规范扫描顺序**：
   **X 为最快变化轴，Z 为次快变化轴，Y 为最慢变化轴**（自底向上扫描水平切片）：

   ```
   index(x, y, z) = (x - min_x) + W * ((z - min_z) + D * (y - min_y))
   ```

3. **方块状态规范化表示**：
   * 空气统一规范化为 `"minecraft:air"`（`cave_air`、`void_air`、`structure_void`、`bubble_column` 均映射为空气）；
   * 属性键严格按 ASCII 字典序升序排序，无多余空格，例如：
     `"minecraft:chest[facing=north,type=single,waterlogged=false]"`；
   * Rust 端只对空气别名与旧版 `{"state":"..."}` 包装做规范化，**不重排属性**——属性排序由服务端 `BlockDataEncoder.serializeBlockState` 保证；两端必须逐字节一致。
   * **未加载区块**：初稿定义的 `"mtk:unloaded"` 当前未实现。服务端扫描通过 `level.getChunk(cx, cz)` 强制加载选区覆盖的区块，因此 Baseline 中不会出现“未加载”占位符（📋 后续可选实现）。

4. **生物群系规范化与不可变契约**：
   * **Live 阶段生物群系不可变**：运行时方块放置/破坏不改变生物群系；Biome 仅在 Baseline 阶段采集并锁定。
   * **Quart 剖面规范化**：选区覆盖的 3D Quart 区域维度为 `Q_W × Q_H × Q_D`，其中
     `Q_W = ceil(W / 4)`、`Q_H = ceil(H / 4)`、`Q_D = ceil(D / 4)`；遍历顺序同样为 `Y → Z → X`。
   * **⚠️ Section-local 写入契约（v2.0 修复）**：
     客户端在重建 `VoxelStorage` 时，必须把每个全局 Quart 锚点 `(wx, wy, wz)` 映射到
     **所在 16³ Section 的局部 Quart 索引**：

     ```
     sec      = (wx >> 4, wy >> 4, wz >> 4)
     sec_qx   = (wx >> 2) & 3
     sec_qy   = (wy >> 2) & 3
     sec_qz   = (wz >> 2) & 3
     ```

     **严禁**直接使用全局 Quart 序号 `qx & 3`。当 `min_pos` 不是 16 对齐时，后者会写入错误的
     Section 局部 Quart 单元，导致多生物群系大选区的 `state_hash` 必然失配、进度永久卡在 75%
     并陷入重同步循环（已由 `test_baseline_alignment.rs` 回归覆盖）。

### 3.2 伪代码计算规范 (xxHash64)

```text
function compute_canonical_state_hash(level, bounds, dimension_str) -> uint64:
    hasher = xxHash64::new(seed = 0)

    // 1. 元信息标头
    hasher.update([0x01])                         // Canonical Encoding Version: u8
    hasher.update(u16_le(dimension_str.len()))
    hasher.update(dimension_str.utf8_bytes())
    hasher.update(i32_le(bounds.min_x))
    hasher.update(i32_le(bounds.min_y))
    hasher.update(i32_le(bounds.min_z))
    hasher.update(u32_le(bounds.size_x))
    hasher.update(u32_le(bounds.size_y))
    hasher.update(u32_le(bounds.size_z))

    // 2. 连续三维体素流 (X-fastest, Z-next, Y-slowest)
    for y from min_y to max_y - 1:
        for z from min_z to max_z - 1:
            for x from min_x to max_x - 1:
                state_str = get_canonical_blockstate(level, x, y, z)
                hasher.update(u16_le(state_str.len()))
                hasher.update(state_str.utf8_bytes())

    // 3. 连续 3D Quart 生物群系流 (4x4x4 降采样网格)
    for qy from 0 to ceil(H / 4) - 1:
        for qz from 0 to ceil(D / 4) - 1:
            for qx from 0 to ceil(W / 4) - 1:
                biome_str = get_canonical_quart_biome(level, qx, qy, qz)
                hasher.update(u16_le(biome_str.len()))
                hasher.update(biome_str.utf8_bytes())

    return hasher.digest()
```

> **实现注意**：服务端在扫描 Level 的原始数据上计算；客户端在组装完成的 `VoxelStorage` 上重算。
> 两者必须使用完全一致的规范化字符串与 Quart 映射，否则会在 `BASELINE_END` 阶段报
> `STATE_HASH_MISMATCH`。

---

## 4. 数据报文规范 (Packet Payloads Specification)

### 4.1 `0x01` HELLO（客户端握手发起 C → S）

```
Offset | Type     | Description
-------+----------+-------------------------------------------------------------
0..3   | Header   | Magic ('M', 'T'), Ver (0x03), Opcode (0x01)
4..5   | uint16   | Min Protocol Version Supported (0x0003)
6..7   | uint16   | Max Protocol Version Supported (0x0003)
8..11  | uint32   | Client Capabilities Flags:
       |          |   Bit 0: Supports Zstd
       |          |   Bit 1: Supports DNA Direct Memory
12..15 | uint32   | Client Request Flags:
       |          |   Bit 0: FORCE_FULL_BASELINE
       |          |   Bit 1: NO_CACHE
       |          |   Bit 2: REQUIRE_BASELINE_IF_USER_MODIFIED
16..31 | bytes    | Cached World UUID (16 字节，全 0 代表无有效缓存)
32..39 | uint64   | Cached Epoch ID
40..47 | uint64   | Cached Sequence ID
48..51 | int32    | Cached Min X
52..55 | int32    | Cached Min Y
56..59 | int32    | Cached Min Z
60..63 | int32    | Cached Size X
64..67 | int32    | Cached Size Y
68..71 | int32   | Cached Size Z
72..79 | uint64   | Cached state_hash (无有效缓存填 0)
80..81 | uint16   | Auth Token Length (T_len)
82..   | bytes    | UTF-8 Auth Token
--     | uint16   | Cached Dimension Name Length (D_len)
--     | bytes    | UTF-8 Cached Dimension Name
```

> **实现备注**：当前 Yefira 服务端解析并保存 HELLO 全部字段，但 `Client Request Flags`
> 尚未参与决策（`FORCE_FULL_BASELINE` / `NO_CACHE` 为预留位，📋）。

#### 4.1.1 认证令牌语义（v3.1 安全加固）

* **服务端**：共享密钥存于 `config/yefira.json` 的 `authToken`，或用
  `/yefira config token <secret>` 设置。`authToken` 为空时服务端只允许绑定回环地址；
  绑定非回环地址但未配置令牌时 `startServer` 直接拒绝启动。
* **校验**：服务端对配置值与 HELLO 中的 `auth_token` **两侧都做 `trim`** 后按字节比较
  （`MessageDigest.isEqual`）。不匹配 → 回 `WELCOME(decision = 0xFF)`
  且 `message = "Authentication failed"`，随后以关闭码 `1008` 断开。
* **客户端**：令牌必须出现在**每一个** HELLO 中，包括重连、以及没有缓存状态时构造的
  默认 HELLO（`cached_*` 全 0）。缓存 HELLO 不得省略令牌，也不得携带过期令牌：
  `LiveSyncSession` 一旦通过 `set_auth_token` 设置令牌，就以会话令牌为准覆盖 HELLO 中的值。
* **Blender**：面板 `Auth Token`（`properties.auth_token`，`subtype=PASSWORD`，
  `SKIP_SAVE`，不写入 `.blend`）→ `bridge/sync.py`（`strip()` 归一化）→
  `LiveSyncSession.start(..., auth_token=...)` / `start_with_persisted_state(...)`。
  token 为空时不传参，等价于空令牌。

> **历史缺陷（v2.0.x 修复）**：`LiveSyncSession` 的默认 HELLO 曾把 `auth_token` 硬编码为空串，
> 只有构造缓存 HELLO 的分支才会带上令牌。Blender 默认禁用快速重连、始终走默认 HELLO，
> 因此服务端一旦配置令牌，即使两端令牌完全相同也会被判为 `Authentication failed`。

### 4.2 `0x02` WELCOME（服务端握手应答 S → C）

```
Offset | Type     | Description
-------+----------+-------------------------------------------------------------
0..3   | Header   | Magic ('M', 'T'), Ver (0x03), Opcode (0x02)
4..5   | uint16   | Negotiated Protocol Version
6..21  | bytes    | Server Instance UUID（服务端重启/换世界即变化）
22..29 | uint64   | Server Epoch ID
30..37 | uint64   | Current Server Sequence ID
38..41 | int32    | Current Min X
42..45 | int32    | Current Min Y
46..49 | int32    | Current Min Z
50..53 | int32    | Current Size X
54..57 | int32    | Current Size Y
58..61 | int32    | Current Size Z
62..69 | uint64   | Current state_hash
70     | uint8    | SyncDecision:
       |          |   0x00 = VERIFIED_SKIP_REBUILD
       |          |   0x01 = REPLAY_DELTAS
       |          |   0x02 = FULL_BASELINE_REQUIRED
       |          |   0xFF = REJECTED
71..72 | uint16   | Reason / Dimension String Length
73..   | bytes    | UTF-8 String
```

#### SyncDecision 决策矩阵（与 `handleClientHello` 一致）

| 判定条件 | 决策结果 | 客户端行为 |
| :--- | :--- | :--- |
| 协议版本协商失败 / 鉴权失败 | `0xFF REJECTED` | 报错并停止同步 |
| Server UUID 不匹配 / 无有效缓存 | `0x02 FULL_BASELINE_REQUIRED` | 清空候选基线，准备全量 |
| Server Epoch 不匹配 | `0x02 FULL_BASELINE_REQUIRED` | 清空候选基线，准备全量 |
| Bounds / Dimension 不匹配 | `0x02 FULL_BASELINE_REQUIRED` | 清空候选基线，准备全量 |
| `cached_seq != server_seq`（含客户端超前） | `0x02 FULL_BASELINE_REQUIRED` | 判定缓存失效 |
| `cached_hash == server_hash` 且 UUID/Epoch/Seq/Bounds/Dimension 全匹配 | `0x00 VERIFIED_SKIP_REBUILD` | 将本地 sequence 提升至 `server_seq`，直接进入 LIVE |
| `cached_seq < server_seq` 且 Delta 保留窗口覆盖缺口 | `0x01 REPLAY_DELTAS` | 挂起网格提交，等待服务端补发（📋 当前服务端不产生该决策） |

> **实现备注**：
> 1. 当前服务端**从不返回** `REPLAY_DELTAS`；客户端收到该决策时会主动请求一次全量基线。
> 2. 快速重连（`VERIFIED_SKIP_REBUILD`）依赖客户端持久化的 `mtk_sync_*` 属性。
>    服务端在**任何方块变更 / 选区变更 / 选区清空**时都会把 `cachedStateHash` 置 0，
>    因此“断线期间世界被修改”不会误触发跳过重建。
> 3. **Blender 端当前默认禁用快速重连**（`_ZERO_REBUILD_FAST_PATH_ENABLED = False`）：
>    Rust 原生 `VoxelStorage` 尚未持久化到 `.blend`。若在空存储上直接进入 `LIVE`，
>    下一条 `DELTA_OP` 只会重构被修改方块所在区块，导致视口网格被覆盖丢失。
>    因此客户端仍会持久化 `mtk_sync_*`（为未来恢复功能做准备），但 `HELLO` 的
>    `cached_*` 字段保持为 0，始终请求全量基线。启用前提见 §8 阶段 C。

### 4.3 `0x03` BASELINE_BEGIN（全量基线元信息 S → C）

```
Offset | Type     | Description
-------+----------+-------------------------------------------------------------
0..3   | Header   | Magic ('M', 'T'), Ver (0x03), Opcode (0x03)
4..11  | uint64   | Epoch ID
12..27 | bytes    | Snapshot UUID
28..35 | uint64   | Snapshot Sequence S
36..39 | int32    | Min X (半开区间 [min_x, max_x))
40..43 | int32    | Min Y
44..47 | int32    | Min Z
48..51 | int32    | Size X (W)
52..55 | int32    | Size Y (H)
56..59 | int32    | Size Z (D)
60..67 | uint64   | Volume state_hash
68..71 | uint32   | Baseline Palette Revision
72..75 | uint32   | Total Chunks Count N
76..83 | uint64   | Total Encoded Payload Bytes
84..91 | uint64   | Total Decoded Voxel Bytes（防解压炸弹预检）
92     | uint8    | Compression Mode (0 = Uncompressed, 1 = Zstd)
93     | uint8    | Palette Bits Per Block (1/2/4/8/16；当前服务端使用 8/16)
94     | uint8    | Biome Bits Per Quart (1/2/4/8/16；多群系时服务端使用 8)
95..96 | uint16   | Dimension Name Length
97..   | bytes    | UTF-8 Dimension String
--     | uint32   | Block Palette 条目数 P
--     | List     | P 个规范 BlockState 字符串
--     | uint16   | Biome Palette 条目数 B
--     | List     | B 个规范 Biome 字符串
```

> 客户端在收到 BEGIN 时：
> 1. 校验 `epoch` 与当前会话一致，否则忽略（过期流）；
> 2. 记录 `snapshot_seq = S` 与 `current_state_hash = state_hash`；
> 3. 重建调色板映射（`palette_map`），**保留**已暂存的 `seq > S` 增量；
> 4. 若选区 bounds 变化，重置连续失败计数。

### 4.4 `0x04` BASELINE_CHUNK（体素数据分块流 S → C）

```
Offset | Type     | Description
-------+----------+-------------------------------------------------------------
0..3   | Header   | Magic ('M', 'T'), Ver (0x03), Opcode (0x04)
4..11  | uint64   | Epoch ID（必须匹配当前 BASELINE_BEGIN）
12..27 | bytes    | Snapshot UUID（严格匹配当前快照）
28..31 | uint32   | Chunk Index (0 .. N-1)
32..35 | uint32   | Total Chunks N
36..43 | uint64   | First Voxel Index
44..47 | uint32   | Voxel Count
48..51 | uint32   | Encoded Payload Length L
52..55 | uint32   | Decoded Target Bytes
56..63 | uint64   | Chunk xxHash64
64..   | bytes    | L 字节有效载荷（体素位流 + 末尾 Quart Biome 流）
```

> **可靠组装与坏包防御契约**：
> 1. Rust 解码器在 `decode_packet` 阶段先校验 `xxHash64`，失败则丢弃该帧并发出
>    `Warning`（不会误判为断线）；
> 2. `First Voxel Index` 必须严格等于上一块的 `First Voxel Index + Voxel Count`；
>    第 0 块必须为 0，严禁重叠或空洞；
> 3. 位打包为 **LSB-first** 紧凑打包，末尾补 0；
> 4. **Biome 尾部规则**：服务端把整个选区的 Biome Quart 流追加在体素流之后，
>    按 256 KiB 字节边界切块。因此只有**包含 Biome 起点的那个分块**（通常是最后一个
>    体素分块）的 `Decoded Target Bytes` 会大于 `Voxel Count × bytesPerVoxel`，
>    其余字节按 Biome 位宽解包；当 Biome 起点恰好落在新的 256 KiB 边界时，
>    会出现 `Voxel Count = 0` 的纯 Biome 分块；
> 5. 组装器检测到序号/校验/结构错误时：丢弃当前基线 → `RESYNC_REQUEST`
>    （reason = `SEQUENCE_GAP` / `CHUNK_CORRUPTED`），由服务端重新下发全新基线；
>    主动放弃（如选区超限）则发送 `CANCEL`。

### 4.5 `0x05` BASELINE_END（全量基线完成信号 S → C）

```
Offset | Type     | Description
-------+----------+-------------------------------------------------------------
0..3   | Header   | Magic ('M', 'T'), Ver (0x03), Opcode (0x05)
4..11  | uint64   | Epoch ID
12..27 | bytes    | Snapshot UUID
28..35 | uint64   | Snapshot Sequence S
36..39 | uint32   | Total Chunks Sent（必须与实际接收数量严格相等）
40..47 | uint64   | Final state_hash（组装后重算必须完全一致）
48     | uint8    | Status (0 = SUCCESS, 1 = ABORTED_BY_SERVER)
```

### 4.6 `0x06` BASELINE_ACK（客户端基线提交确认 C → S）

```
Offset | Type     | Description
-------+----------+-------------------------------------------------------------
0..3   | Header   | Magic ('M', 'T'), Ver (0x03), Opcode (0x06)
4..11  | uint64   | Epoch ID
12..27 | bytes    | Snapshot UUID
28..35 | uint64   | Committed Sequence ID
36     | uint8    | Result Code:
       |          |   0x00 = SUCCESS_COMMITTED
       |          |   0x01 = VALIDATION_FAILED
       |          |   0x02 = BUFFER_OVERFLOW
```

> 当前服务端解析并记录结果码（失败时输出警告）；ACK 超时事务回滚尚未强制实现。

### 4.7 `0x07` DELTA_OP（增量操作日志批次 S → C）

```
Offset | Type     | Description
-------+----------+-------------------------------------------------------------
0..3   | Header   | Magic ('M', 'T'), Ver (0x03), Opcode (0x07)
4..11  | uint64   | Epoch ID（必须匹配当前基线代数）
12..19 | uint64   | Sequence ID（严格连续递增）
20..23 | uint32   | Palette Revision
24..25 | uint16   | Change Count C（1 <= C <= 16,384）
26..33 | uint64   | Batch xxHash64
34..   | List     | C 个原子变动条目:
       |   int32  - Relative X (0 <= rel_x < W)
       |   int32  - Relative Y (0 <= rel_y < H)
       |   int32  - Relative Z (0 <= rel_z < D)
       |   uint16 - Palette State ID
```

> **实现备注**：
> 1. 服务端 `broadcastDeltaUpdate` 按 **16,384 条/批** 自动切分，每批占用独立、连续的
>    `sequence`；`flushQueuedDeltaUpdates` 中排队的变更上限为 262,144 条，超出后自动
>    退化为一次全量 Baseline 广播。
> 2. 同一批次内出现重复坐标时，按数组顺序依次写入 `VoxelStorage`，效果等价于
>    **Last-Write-Wins**。
> 3. 相对坐标越界视为协议错误；客户端应按 `ERROR(INVALID_BOUNDS)` 处理（当前实现会
>    写入越界位置并由 `VoxelStorage` 边界保护丢弃，📋 后续可加显式校验）。

### 4.8 `0x08` PALETTE_UPDATE（动态调色板有序追加 S → C）

```
Offset | Type     | Description
-------+----------+-------------------------------------------------------------
0..3   | Header   | Magic ('M', 'T'), Ver (0x03), Opcode (0x08)
4..11  | uint64   | Epoch ID
12..19 | uint64   | Sequence ID（与同批次 DELTA_OP 共享）
20..23 | uint32   | Base Palette Revision
24..27 | uint32   | New Palette Revision (Base + 1)
28..29 | uint16   | New Entries Count K
30..   | List     | K 个新增条目:
       |   uint16 - State ID
       |   uint16 - State String Length
       |   bytes  - UTF-8 BlockState String
```

> **实现对齐说明**：初稿曾要求 `PALETTE_UPDATE` 占用独立的连续序号。当前实现中，
> 调色板追加被视为所在 Delta 批次的附属元数据，**与 `DELTA_OP` 共享同一个 `Sequence ID`**，
> 并通过 `palette_revision` 的单调递增保证一致性。客户端不会为 `PALETTE_UPDATE`
> 推进 `sequence`，而是直接更新本地调色板映射。

### 4.9 `0x0D` RESYNC_REQUEST（增量缺口与错误恢复请求 C → S）

```
Offset | Type     | Description
-------+----------+-------------------------------------------------------------
0..3   | Header   | Magic ('M', 'T'), Ver (0x03), Opcode (0x0D)
4..11  | uint64   | Epoch ID
12..19 | uint64   | Missing From Sequence
20..27 | uint64   | Missing To Sequence
28     | uint8    | Reason:
       |          |   0x01 = SEQUENCE_GAP
       |          |   0x02 = PALETTE_REVISION_MISMATCH
       |          |   0x03 = STATE_HASH_MISMATCH
       |          |   0x04 = CHUNK_CORRUPTED
```

#### 服务端响应规则（当前实现）

* 当前服务端**不做 Delta 环形缓冲补发**：收到 `RESYNC_REQUEST` 后，立即为该客户端
  启动一条全新的 Baseline 流（旧流通过代际失效）。
* 初稿中的“保留窗口内补发缺失 DELTA”属于后续优化项（📋）。
* 客户端侧：
  * 自动重同步请求限流 **900ms**；
  * 同一选区连续 **3 次** 基线校验失败后暂停自动重试，UI 显式提示
    “点击 Refresh 或更换选区后重试”；
  * 手动 `Refresh` 会清零失败计数并重新请求全量快照。

### 4.10 `0x09` STATE_VERIFY_REQ（状态校验请求，双向）

```
Offset | Type     | Description
-------+----------+-------------------------------------------------------------
0..3   | Header   | Magic ('M', 'T'), Ver (0x03), Opcode (0x09)
4..11  | uint64   | Epoch ID
12..19 | uint64   | Current Sequence ID
20..27 | uint64   | Volume state_hash
```

### 4.11 `0x0A` STATE_VERIFY_RESP（状态校验应答，双向）

```
Offset | Type     | Description
-------+----------+-------------------------------------------------------------
0..3   | Header   | Magic ('M', 'T'), Ver (0x03), Opcode (0x0A)
4..11  | uint64   | Epoch ID
12..19 | uint64   | Current Sequence ID
20     | uint8    | IsMatch (1 = 匹配, 0 = 不匹配)
```

> 当前 `0x09/0x0A` 已由 Rust 编解码器与 Java 常量定义，但未纳入实际会话流程（📋 预留）。

### 4.12 `0x0B` CANCEL（任务主动取消，双向）

```
Offset | Type     | Description
-------+----------+-------------------------------------------------------------
0..3   | Header   | Magic ('M', 'T'), Ver (0x03), Opcode (0x0B)
4..11  | uint64   | Epoch ID
12..27 | bytes    | Snapshot UUID（全 0 代表取消当前 Epoch 全部任务）
28     | uint8    | Cancel Reason:
       |          |   0x01 = SELECTION_CHANGED
       |          |   0x02 = USER_ABORT
       |          |   0x03 = REASON_BAD_CHUNK
       |          |   0x04 = TIMEOUT
```

> **当前实现**：
> * 客户端在 `BaselineAssembler::new` 失败（如选区体积超限）时发送 `CANCEL`；
> * 服务端收到 `CANCEL` 后立即递增该客户端的流代际，停止剩余分块发送；
> * 服务端也可能主动发送 `CANCEL`（例如资源限制）；客户端收到后清空当前组装器并等待新快照。

### 4.13 `0x0E` PING & `0x0F` PONG（连接保活独立 Opcode）

```
Offset | Type     | Description
-------+----------+-------------------------------------------------------------
0..3   | Header   | Magic ('M', 'T'), Ver (0x03), Opcode (0x0E / 0x0F)
4..11  | uint64   | Timestamp (毫秒时间戳，用于计算 RTT)
```

> Rust 客户端与 Yefira 均实现了应用层 PING/PONG 编解码与应答；
> 当前保活主要依赖 WebSocket 协议层 Ping/Pong。应用层 20s 定时 PING 尚未调度（📋）。

### 4.14 `0x10` ERROR（统一错误响应，双向）

```
Offset | Type     | Description
-------+----------+-------------------------------------------------------------
0..3   | Header   | Magic ('M', 'T'), Ver (0x03), Opcode (0x10)
4..11  | uint64   | Related Epoch ID
12..13 | uint16   | Error Code:
       |          |   0x0001 = UNSUPPORTED_VERSION
       |          |   0x0002 = INVALID_BOUNDS
       |          |   0x0003 = SEQUENCE_GAP_UNRECOVERABLE
       |          |   0x0004 = CHECKSUM_MISMATCH
       |          |   0x0005 = RESOURCE_LIMIT_EXCEEDED
       |          |   0x0006 = PERMISSION_DENIED
       |          |   0x0007 = UNKNOWN_OPCODE
       |          |   0x0008 = INVALID_PALETTE
14..15 | uint16   | Error Message Length
16..   | bytes    | UTF-8 Detailed Diagnostic Message
```

> **当前实现**：服务端在选区超过 32M 体素硬限时发送 `ERROR(0x0005)`，
> 客户端将其显示为 `Error: ...` 并停止流式进度，但保持连接，等待用户缩小选区或手动刷新。

---

## 5. 状态机与一致性栅栏契约 (State Machine & Barriers)

### 5.1 客户端生命周期状态转换图（与 `SyncLifecycle` 枚举一致）

```text
                  +--------------------+
                  |    DISCONNECTED    |
                  +--------------------+
                            │ connect()
                            ▼
                  +--------------------+
                  |     CONNECTING     |
                  +--------------------+
                            │ onOpen -> send HELLO
                            ▼
                  +--------------------+
                  |    NEGOTIATING     |
                  +--------------------+
                            │
        ┌───────────────────┴───────────────────┐
        │ SyncDecision == 0x00 VERIFIED         │ SyncDecision == 0x02 FULL_BASELINE
        ▼                                       ▼
+----------------+                     +--------------------+
|  (VERIFYING)   |                     | RECEIVING_BASELINE |
|  预留状态      |                     +--------------------+
+----------------+                              │ BASELINE_END
        │                                       ▼
        │                             +--------------------+
        │                             |  VALIDATING_HASH   |
        │                             +--------------------+
        │                                       │ state_hash 匹配
        │                                       ▼
        │                             +--------------------+
        │                             |  REPLAYING_STAGED  | S+1..latest 有序重放
        │                             +--------------------+
        │                                       │
        │                                       ▼
        │                             +--------------------+
        │                             |   BUILDING_MESH    | Rayon 并行网格化
        │                             +--------------------+
        │                                       │ WorldMeshReady
        │                                       ▼
        │                             +--------------------+
        │                             | 宿主 DNA/Buffer    | Blender 主线程注入
        │                             | 生成校验 + 持久化  |
        │                             +--------------------+
        └──────────────────────────────────────► LIVE
```

> `SyncLifecycle::Verifying` 为预留枚举值；当前 `VERIFIED_SKIP_REBUILD` 直接进入 `LIVE`。
> `COMMITTING_DNA` 不属于 Rust 会话状态机：它由宿主在收到 `WorldMeshReady` 后执行。

### 5.2 Baseline 与 Delta 的严密交错处理

1. **未收到 `BASELINE_BEGIN` 前的在途 Delta**：
   * 客户端在 `WELCOME` 后进入 `FULL_BASELINE_REQUIRED`，任何匹配 `Epoch` 的 `DELTA_OP`
     都会进入 Staging Buffer（`RECEIVING_BASELINE` 及所有非 `LIVE` 状态）。
   * 旧 `Epoch` 的 `DELTA_OP` 直接丢弃。
   * `BASELINE_BEGIN` **不会清空** Staging Buffer：`seq <= S` 的包在重放阶段被丢弃，
     `seq > S` 的包必须保留并重放。
2. **Snapshot Sequence `S` 的栅栏对齐**：
   * `BASELINE_BEGIN.snapshot_seq = S`；
   * 客户端设置 `sequence = S`，期望下一包为 `S + 1`；
   * `BASELINE_END` 且哈希校验通过后：
     * 丢弃 Staging Buffer 中所有 `<= S` 的过期包；
     * 从 `S + 1` 开始严格按序重放；
     * 若首个暂存包 `> S + 1`，判定缺口 → `RESYNC_REQUEST`；
     * 重放完成后构建网格并提交 `BASELINE_ACK(SUCCESS_COMMITTED)`；
     * 网格构建期间到达的增量继续暂存，构建完成后再次排空并触发脏区重建。
3. **Delta 缺口处理**：
   * `seq == expected` → 应用并 `pending_dirty_rebuild = true`；
   * `seq < expected` → 重复包，忽略；
   * `seq > expected` → 丢弃当前 live 状态、进入等待基线并发送 `RESYNC_REQUEST(SEQUENCE_GAP)`。

### 5.3 服务端基线代际与 Delta 调色板一致性（v2.0 修复）

服务端在 `WebSocketServerManager` 中维护三层隔离：

1. **Per-Client Stream Generation**：
   每个客户端持有一个单调递增的 `streamGen`。新的握手/刷新/重同步/`CANCEL`
   都会先递增代际，再异步提交扫描任务。旧任务在扫描循环、每个分块发送前都会检查
   `isStreamCurrent(...)`，一旦失效立即退出，不再占用 CPU/内存，也不再向 socket 写入旧快照。
2. **Selection Generation**：
   任一选区变化都会递增全局 `selectionGeneration`，使所有客户端的旧扫描任务同帧失效。
3. **Per-Client Send Lock**：
   所有基线帧在锁内做“代际检查 + 发送”，保证同一连接上不会出现两条流交错；
   并发的新流会等待旧流当前帧发送完成后再发送自己的 `BASELINE_BEGIN`。

Delta 调色板一致性：

* 基线扫描与推流期间，`activeBaselineStreams > 0`，`flushQueuedDeltaUpdates` 会**延迟**广播；
* `broadcastDeltaUpdate` 在 `paletteLock` 内二次检查该计数，避免窗口期用旧调色板编码新序号；
* 基线完成后，延迟的变更使用新快照调色板重新编码并以 `S + 1...` 连续序号发送；
* `snapshot_seq = S` 在扫描**开始前**、于 `paletteLock` 内捕获，确保扫描期间产生的
  方块变更序号必然 `> S`，从而被客户端安全重放。

### 5.4 可恢复性守护 (Recovery Guards)

| 守护 | 行为 |
| :--- | :--- |
| **Baseline Watchdog** | `RECEIVING_BASELINE` 20s / `VALIDATING_HASH`+`REPLAYING_STAGED` 10s 无进展 → 丢弃半截基线 + `RESYNC_REQUEST` |
| **Resync Rate Limit** | 自动重同步请求间隔 ≥900ms，避免坏流触发风暴 |
| **Failure Budget** | 同一选区连续 3 次校验失败 → 停止自动重试并报错；手动 Refresh / 新选区重置 |
| **Stale Frame Filter** | 忽略 `epoch/uuid/total_chunks` 不匹配的 BEGIN/CHUNK/END，避免旧流污染新流 |
| **Worker Liveness Guard** | worker 线程异常/管道关闭时保证发出终态 `DISCONNECTED`；锁中毒自动恢复；单包处理 panic 捕获并恢复 |
| **Session Reset** | 每次 `start()` 重置生命周期/序号/调色板/组装器/暂存队列，并清空遗留网格事件 |
| **Oversized Guard** | 服务端与客户端均在扫描/分配前拒绝 >33,554,432 体素的选区 |

---

## 6. Blender DNA 零拷贝与场景持久化契约 (DNA Ingestion & Persistence)

### 6.1 MeshData 与 Blender CustomData 内存对齐规范

DNA 裸指针写入（`inject_topology_dna` / `copy_positions_to_ptr` 等）必须严格遵守
Blender 4.2+ / 5.0 的 C 内存布局规范：

* **顶点位置 (Positions)**：连续 `float32[3]`，步长 12 字节；
* **面 Corner 顶点 (Loops)**：连续 `int32`，步长 4 字节；
* **UV 坐标 (Loop UVs)**：连续 `float32[2]`，步长 8 字节；
* **面材质插槽索引 (Material Index)**：连续 `int16`（Blender 4.2）或 `int32`（Blender 5.0+），
  由 `DnaResolver` 动态决定；
* **顶点颜色/染色 (Colormap UV & Tint)**：连续 `float32[4]` (RGBA Linear) 或 `float32[2]`。

### 6.2 事务隔离与回滚准则

1. **代数原子核验**：
   Blender 主线程在执行网格写入前，必须比较：
   ```
   mesh_data.generation >= active_container["mtk:client_generation"]
   ```
   * generation 由原生会话单调递增；
   * **每次 Connect 必须把根容器的 `mtk:client_generation` 重置为 0**，
     防止 `.blend` 中遗留的高代数把新会话的网格全部判为“过期”而静默丢弃；
   * 原生会话 `start()` 会清空上一连接遗留的 `WorldMeshReady` 事件，避免旧网格注入新会话。

2. **场景原子持久化**：
   只有在网格成功注入 Blender 之后，才在根容器上一次性原子更新：

   | 属性 | 类型 | 说明 |
   | :--- | :--- | :--- |
   | `mtk_sync_server_uuid` | String | 服务端实例 UUID（32 位 hex） |
   | `mtk_sync_epoch` | int | 服务端代数 |
   | `mtk_sync_sequence` | int | 已提交的最新序列号 |
   | `mtk_sync_bounds` | `[int; 6]` | `[min_x, min_y, min_z, size_x, size_y, size_z]` |
   | `mtk_sync_dimension` | String | 维度标识 |
   | `mtk_sync_state_hash` | String | `"0x" + 16 位 hex` |
   | `mtk_sync_user_modified` | bool | 用户是否手工修改过场景（默认 False，阻止快速跳过） |

   这些字段是 RFC v3.1 快速重连的候选输入。**当前 Blender 端默认不把它们填入
   `HELLO.cached_*`**，因为原生 `VoxelStorage` 未随 `.blend` 持久化；仅持久化
   属性并不能让 Rust 侧在 `VERIFIED_SKIP_REBUILD` 后继续正确应用增量。
   在实现 VoxelStorage 持久化/恢复之前，连接一律走全量基线（安全优先）。

3. **快速重连失效规则（服务端）**：
   * 任何方块变更（`queueDeltaUpdate`）→ `cachedStateHash = 0`；
   * 选区变化 / 选区清空 → `cachedStateHash = 0`；
   * 服务端重启 → `server_uuid` 变化；
   * 任一不匹配 → `FULL_BASELINE_REQUIRED`，绝不使用过期缓存跳过重建。

---

## 7. 实现对齐矩阵与已知偏差 (Implementation Matrix & Deviations)

### 7.1 对齐矩阵

| RFC 条目 | 实现位置 | 状态 |
| :--- | :--- | :--- |
| 4 字节帧头 / Magic `MT` / Ver `0x03` | `codec.rs`, `BlockDataEncoder.java` | ✅ |
| 资源硬限与解压炸弹防护 | `protocol/constants.rs`, `codec.rs` | ✅ |
| `MaxSelectionVolume` 双重校验 + ERROR | `assembler.rs`, `WebSocketServerManager` | ✅（v2.0 修复） |
| Canonical `state_hash` | `hasher.rs`, `CanonicalVoxelScanner.java` | ✅ |
| Section-local Quart Biome 映射 | `session/assembler.rs` | ✅（v2.0 修复） |
| HELLO / WELCOME / 决策矩阵 | `codec.rs`, `handleClientHello` | ✅（`REPLAY_DELTAS` 未产生） |
| HELLO `auth_token` 认证 | `session/hello.rs`（默认/缓存 HELLO）、`mtk-py` 绑定、`isAuthorized` | ✅（v2.0.x 修复：默认 HELLO 曾丢失令牌） |
| BASELINE_BEGIN / CHUNK / END | `assembler.rs`, `streamBaseline` | ✅ |
| BASELINE_ACK | 客户端发送，服务端记录 | ⚠️ 无 ACK 超时 |
| Delta 16,384 分片 | `broadcastDeltaUpdate` | ✅（v2.0 修复） |
| Delta Staging + Snapshot Replay | `staging.rs`, `dispatcher.rs` | ✅ |
| PALETTE_UPDATE 与批次共享序号 | `broadcastDeltaUpdate` | ✅（文档已按实现修正） |
| RESYNC_REQUEST | 客户端 + 服务端整包重发 | ✅（无 Delta 窗口补发） |
| STATE_VERIFY_REQ/RESP | 编解码已实现 | 📋 未接入会话 |
| CANCEL 双向取消 | 客户端 + 服务端代际失效 | ✅（v2.0 修复） |
| PING / PONG | 编解码 + 应答 | ⚠️ 无应用层定时器 |
| ERROR(0x10) | 编解码 + 超限/资源错误 | ✅（v2.0 修复） |
| 快速重连持久化 | Python `persist_sync_session_state` + Rust getters + Java 失效规则 | ⚠️ 服务端判定已完备；Blender 端默认禁用（等待 VoxelStorage 持久化） |
| 基线看门狗 / 限流 / 失败熔断 | `dispatcher.rs` | ✅（v2.0 修复） |
| Worker 异常终态保证 | `WorkerExitGuard` + `catch_unwind` | ✅（v2.0 修复） |
| 宿主连接状态权威同步 | `bridge/sync.py`, `_sync_timer_tick` | ✅（v2.0 修复） |

### 7.2 与 RFC 初稿的刻意偏差

1. **`PALETTE_UPDATE` 序号**：与同批次 `DELTA_OP` 共享 `Sequence ID`，不单独推进序号。
2. **`REPLAY_DELTAS`**：服务端未维护 Delta 环形缓冲，恢复统一走全量 Baseline。
3. **超时数值**：基线看门狗为 20s/10s，而非“每分块 10s”；ACK 超时未实现。
4. **Keepalive**：依赖 WebSocket 协议层 Ping/Pong；应用层 20s PING 定时器未实现。
5. **`mtk:unloaded`**：未引入；扫描时强制加载选区覆盖的区块。
6. **`STATE_VERIFY_*`**：Opcode 已预留，会话流程未使用。
7. **`SyncLifecycle::Verifying`**：枚举预留，`VERIFIED_SKIP_REBUILD` 直接进入 `LIVE`。
8. **`COMMITTING_DNA`**：不属于 Rust 状态机，由 Blender 主线程以 `WorldMeshReady` 驱动。
9. **`MaxMessageSize`**：实现常量为 512 KiB（目标值允许上限），服务端 payload 切片 256 KiB。
10. **零重建快速路径**：服务端 `VERIFIED_SKIP_REBUILD` 判定与客户端属性持久化均已实现，
    但 Blender 端默认将 `HELLO.cached_*` 置零。原因是原生 `VoxelStorage` 尚未持久化，
    跳过基线会导致后续增量在空存储上重构并覆盖视口。

### 7.3 v2.0 稳定性修复索引（本次对齐）

| 问题 | 根因 | 修复 |
| :--- | :--- | :--- |
| 大选区卡在 75% | 非 16 对齐 + 多群系时 Section-local Quart 映射错误，`state_hash` 永久失配 | `assembler.rs` 使用 `(world >> 2) & 3`；新增 `test_baseline_alignment.rs` |
| 刷新偶发“未连接” | 终态 `DISCONNECTED` 事件在 worker 退出后未被消费；UI 用字符串推断连接 | 先排空事件再判断存活；`WorkerExitGuard`；UI 以原生 `is_connected` 为准；Refresh 精确提示 |
| 多次移动大选区后重连无数据 | 多流交错、旧流不可取消、扫描无上限、半截会话状态未重置、`.blend` 遗留高 generation | Per-client/Selection 代际；协作取消；固定 2 线程扫描池；32M 硬限；`start()` 全量 reset；Connect 重置 `mtk:client_generation` |
| 重同步风暴 | 过期 CHUNK/END 仍触发恢复 | 忽略过期快照帧；900ms 限流；连续 3 次失败熔断 |
| 基线期间 Delta 调色板错位 | 基线扫描期间用旧调色板广播新序号 | 基线期间延迟 Delta；`paletteLock` 内二次检查；`S` 在扫描前捕获 |
| 工作线程静默死亡 | panic / 锁中毒 / 通道关闭 | `catch_unwind` + 锁中毒恢复 + 终态守卫 |

---

## 8. 版本迁移与实现路径规划

### 阶段 A：协议冻结与三端接口闭环（✅ 已完成）

* **Yefira (Java)**：移除旧 `BlockModelExtractor` 体系；实现规范连续扫描器与 xxHash64；
  实现 HELLO 解析与 SyncDecision 判定；实现 Baseline/Delta/Palette/ACK/ERROR。
* **mtk-sync (Rust)**：实现 Protocol v3.1 解包器与帧对齐；实现 Staging、Snapshot Sequence
  与 Gap Detection；实现单一世界大网格会话。
* **MoziToolKit (Python)**：统一单网格容器；DNA/`foreach_set` 注入；事件泵与持久化。

### 阶段 B：稳定性与一致性加固（✅ 已完成，对应 v2.0 修复）

* Section-local Biome Quart 修复与回归测试；
* Per-client 基线代际、协作取消、固定扫描池；
* 基线期间 Delta 延迟与调色板一致性；
* Baseline Watchdog、Resync 限流、失败熔断；
* 连接状态权威同步、Worker 终态保证；
* 快速重连持久化与失效规则；
* Delta 16,384 分片；
* HELLO 认证令牌（默认/缓存 HELLO 统一携带，两端 trim 归一化）。

### 阶段 C：后续优化（📋 规划）

* 应用层 20s PING 定时器与 45s 掉线判定；
* 15s Baseline ACK 超时与事务回滚；
* 5s 握手超时；
* Delta 环形缓冲区（`REPLAY_DELTAS` 窗口补发）；
* `STATE_VERIFY_REQ/RESP` 心跳校验接入；
* `mtk:unloaded` 未加载区块占位语义；
* Delta 相对坐标越界的显式 `ERROR(INVALID_BOUNDS)` 校验；
* **原生 `VoxelStorage` 持久化/恢复**：完成后即可安全启用
  `_ZERO_REBUILD_FAST_PATH_ENABLED`，真正打通 RFC §6.2 的零重建重连。

---

## 9. 变更记录（RFC 对齐）

| 日期 | 变更 |
| :--- | :--- |
| 2026-10 | 将 RFC 初稿纳入代码文档；按 v2.0 实现修正 75% 卡死、连接状态、重连无数据等章节；补充 Section-local Quart 契约、Delta 分片、快速重连失效规则、代际栅栏与可恢复性守护；记录 10 项已知偏差。 |
| 2026-10 | 新增 §4.1.1 `auth_token` 认证语义；修复 Rust 默认 HELLO 丢失令牌导致的“令牌相同仍认证失败”，三端统一 trim 归一化。 |
