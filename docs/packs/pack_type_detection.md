# 资源包 / JAR 内容识别与自动分类 (Pack Type Detection)

> 代码入口：[`utils/pack_detect.py`](../../utils/pack_detect.py)（纯判定）、
> [`ui/preferences_packs.py`](../../ui/preferences_packs.py)（调度与写回）。
> 相关规范：[三层物理优先级栈](../materials/material_pipeline.md#11-三层物理优先级栈体系-three-tier-priority-stack)。

---

## 1. 为什么不再用文件名判断

历史实现（`on_pack_path_changed`）只看扩展名与文件名里的 `fabric` / `forge` / `mod` 关键字，
在真实资产上会稳定误判：

| 输入 | 文件名启发式 | 真实内容 | 后果 |
| :--- | :--- | :--- | :--- |
| `26.2-Fabric.jar` | `MOD_JAR` | 原版客户端 | 原版基底被塞进模组层，`VANILLA` 层缺失，贴图回退断链 |
| `Connected Glass.jar`（CTM 包常见分发格式） | `VANILLA` | 材质包 | 用户材质包被当成基底，优先级反而最低 |
| `Modern Glass mod.jar` | `MOD_JAR` | 材质包 | 同上 |
| `client.jar`（改名后的 Forge 模组） | `VANILLA` | 模组 | 模组资源被当成原版基底 |

因此判定改为读取压缩包**内容**：ZIP 中央目录里的条目名 + 少量元数据文件。

---

## 2. 判定流程

```text
路径存在?
  ├─ 目录 → 单层 scandir + 关键文件存在性 → 打分
  └─ 文件 → zipfile.ZipFile(只读中央目录，不解压)
              │
              ├─ 单层包裹目录归一化 (MyPack/pack.mcmeta → pack.mcmeta)
              ├─ 根路径精确匹配签名 → 加权累加
              ├─ 命中 pack.mcmeta / version.json / fabric.mod.json 时读取 ≤64KB
              └─ 最高分 - 次高分 → confidence
                        │
                        └─ confidence ≥ 0.15 且 kind 可映射 → suggested_pack_type
```

三条硬性约束：

1. **只读中央目录**：`zipfile.ZipFile()` 不触碰任何条目数据；只有元数据文件会被读取，且
   上限为 64KB（`META_LIMIT`），压缩炸弹与超大 `pack.mcmeta` 都不会造成解压开销。
2. **根路径精确匹配，禁止子串**：原版客户端 JAR 内部就带有
   `data/minecraft/datapacks/*/pack.mcmeta` 与根 `pack.png`；用 `b"pack.mcmeta" in 中央目录`
   会直接误判（已实测）。所有签名都必须精确等于归档根下的相对路径。
3. **打分而非首个命中**：Forge universal JAR 同时携带 `META-INF/mods.toml` 与
   `pack.mcmeta` + `assets/`，必须靠权重让模组标记胜出。

---

## 3. 签名权重表

| 判定 | 证据（根路径精确匹配） | 权重 |
| :--- | :--- | ---: |
| 原版客户端 | 根 `version.json` | 30 |
| 原版客户端 | `net/minecraft/client/main/Main.class` | 30 |
| 原版客户端 | `net/minecraft/client/Minecraft.class` | 20 |
| 原版客户端 | `assets/.mcassetsroot` | 25 |
| 原版客户端 | `data/.mcassetsroot` | 10 |
| 原版客户端 | `META-INF/MOJANGCS.*` 签名 | 25 |
| 原版服务端 | `META-INF/versions.list` + `META-INF/libraries.list` | 40 |
| 原版服务端 | `net/minecraft/bundler/Main.class` | 30 |
| 原版服务端 | `net/minecraft/server/Main.class`（且无客户端标记） | 25 |
| 模组 | `fabric.mod.json` / `quilt.mod.json` | 40 |
| 模组 | `META-INF/mods.toml` / `META-INF/neoforge.mods.toml` | 40 |
| 模组 | `MANIFEST.MF` 含 `FMLModType` / `ModLoader` | 30 |
| 模组 | `META-INF/jars/*.jar`（Jar-in-Jar） | 20 |
| 模组 | 根级 `*.mixins.json` | 15 |
| 模组 | `META-INF/services/*` | 5 |
| 模组 | 存在 `.class` 且无 `pack.mcmeta` | 5 |
| 资源包 | 根 `pack.mcmeta` + `assets/` | 35 |
| 资源包 | 仅有 `assets/` | 15 |
| 资源包 | 根 `pack.png` 且无 class | 10 |
| 资源包 | `assets/minecraft/textures/` | 5 |
| 数据包 | 根 `pack.mcmeta` + 仅 `data/` | 35 |
| 整合包 | `modrinth.index.json` | 40 |
| 整合包 | `manifest.json` + `overrides/` | 40 |

`net/minecraft/server/Main.class` 单独出现**不足以**判定服务端：现代客户端 JAR 同时包含
客户端与服务端类。该签名只有在没有任何客户端标记时计分。

---

## 4. 类型映射与可纠正策略

内部判定结果比 UI 的三层栈更细：

| 内部 kind | 建议 `pack_type` | 可参与烘焙 |
| :--- | :--- | :--- |
| `VANILLA_CLIENT` / `VANILLA_SERVER` | `VANILLA` | ✅ |
| `MOD` | `MOD_JAR` | ✅ |
| `RESOURCE_PACK` | `RESOURCE_PACK` | ✅ |
| `DATA_PACK` | `None`（保持现状 + 面板告警） | ❌ 无贴图 |
| `MODPACK` | `None`（保持现状 + 面板告警） | ❌ 未解包 |
| `UNKNOWN` | `None` | ❌ |

纠正策略由 `pack_type_source` 承担：

- `AUTO`（默认）：内容识别可以覆盖 `pack_type`，路径变化、切换回 AUTO、点击
  「重新识别」都会重新判定。
- `MANUAL`：用户在下拉框里手动选过类型后自动写入，此后**任何自动识别都不会再改**
  `pack_type`（仅记录 `detected_kind` 供面板展示）。

对应纯函数 `resolve_pack_type(current, source, probe)`，不依赖 `bpy`，可直接单测。

**历史配置迁移**：偏好设置面板首次初始化（`is_initialized` 由 False 变 True）时，代码会为
`pack_type_source == AUTO` 且 `detected_kind` 仍为空的条目排队一次探测（`schedule_pending_pack_detection`）。
整个过程走防抖 + 工作线程，打开面板不会因为若干净 JAR 而卡顿。

---

## 5. 性能与「为什么不下沉 Rust」

实测（macOS，Blender 5.2.1 内置 Python 3.13 复测一致）：

| 场景 | 条目数 | 首次探测 |
| :--- | ---: | ---: |
| 原版 26.2 客户端 JAR（39 MB） | 31,709 | 37–49 ms |
| 合成 12k 条目材质包 | 12,006 | ~20 ms |
| 合成 50k 条目材质包 | 50,004 | 106–133 ms |
| 真实材质包（852 / 79 / 16 条目） | — | 0.1–3.5 ms |
| Forge universal JAR | 1,954 | 3.4 ms |
| yefira 模组 JAR | 74 | 0.7 ms |

结论：成本由**条目数**决定，且其中约 90% 是 `zipfile` 解析中央目录本身；我们的加权判定只占
5–8 ms。理论上限实验（只读中央目录字节块 + 精确边界匹配）可到 ~3 ms，说明 Python 侧仍有
约 10 倍余量 —— 需要更快时优化封装，而不是换语言。

因此判定留在 Python 胶水层：

- 属于宿主侧元数据判定，不属于 AGENT.md §3.1 要求下沉的重计算；
- `libmtk_py` 在 mock / 未构建环境为 `None`，UI 判定必须有纯 Python 兜底；
- Rust 现有的 `ZipPack::from_file` 会把**所有条目解压进内存**，只用于判类型是灾难性浪费，
  必须另写只读中央目录的函数并顺带升 API 版本号、重建 `.so`。

真正需要下沉的触发条件（届时新增 `mtk.detect_pack(path)`，Python 保留 fallback）：

1. 无头场景（`mtk-cli` / CI 预编译）也需要同一套判定；
2. 需要递归展开 Jar-in-Jar 并汇总内层模组；
3. 需要把 role 编入 `mtk-package` 缓存指纹；
4. 需要一次性扫描整个 `mods/` 目录（数百个 JAR）。

---

## 6. 调度：为什么判定不能同步跑在 update 回调里

`path` 是 `FILE_PATH` 字符串属性，输入过程中每次按键都会触发 `update`。把 39 MB 归档的
中央目录解析直接塞进回调，在本地是 40 ms 卡顿，在网络盘（SMB/NAS）上会变成数秒假死。

实现采用「防抖 + 工作线程 + 主线程写回」：

```text
on_pack_path_changed  →  仅入队 (路径, deadline=now+150ms)，1.3 ms 返回
_pack_probe_tick      →  bpy.app.timers，主线程；到点起 daemon 线程
_pack_probe_worker    →  纯 Python 判定（无 bpy，线程安全）
_pack_probe_tick      →  队列取回结果，在主线程写 PropertyGroup → 重排 → 落盘 → 重绘
```

- 结果按 `(realpath, size, mtime_ns)` 缓存（LRU 128），重复编辑同一路径为 0 开销；
- `peek_cached_probe()` 只查内存缓存，面板 `draw` 不做任何文件 I/O；
- 单次探测超过 10 s 视为卡死（网络盘），丢弃 inflight 记录允许重试；
- 无 `bpy.app.timers` 的宿主（pytest / mock）自动退化为同步执行，便于测试。

---

## 7. 测试

- `tests/test_pack_detect.py`：判定矩阵、对抗样本（原版 JAR 内嵌数据包 `pack.mcmeta`、
  Forge universal、资源包以 `.jar` 分发、包裹目录、数据包/整合包、损坏与空包）、缓存与失效。
- `tests/test_pack_type_autodetect.py`：AUTO/MANUAL 策略、面板绘制、配置往返、
  操作符注册、`mozi.pack_detect` 行为。

```bash
cd MoziToolKit
../libmozitoolkit/.venv/bin/python -m pytest tests/test_pack_detect.py tests/test_pack_type_autodetect.py -q
```
