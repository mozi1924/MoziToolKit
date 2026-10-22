# 外部导入兼容配置 (Import Compatibility Profile)

外部导入（Mineways / jmc2obj / 模组包）的命名差异不再只靠 Rust 硬编码处理。默认规则位于
[`configs/import_compat.json`](../../configs/import_compat.json)，可在不重编译 Rust 的前提下修改。

## 1. 配置格式

```json
{
  "version": 1,
  "strip_biome_suffixes": ["_forest", "-desert", "..."],
  "material_fallbacks": [
    { "keyword": "leaves", "candidates": ["block/oak_leaves", "minecraft:block/oak_leaves"] }
  ],
  "tint_categories": { "modid:block/custom_grass": "grass" },
  "hardcoded_colors": { "modid:block/custom_leaves": [0.2, 0.6, 0.2, 1.0] }
}
```

- `strip_biome_suffixes`：`clean_identifier` 识别并剥离的旧导出器后缀。`null` 表示使用内置默认；`[]` 表示禁用。
- `material_fallbacks`：关键词 → 候选图集键列表，按顺序查找。`null` 使用内置 leaves/leaf/log 规则；`[]` 禁用。
- `tint_categories`：纹理键 → `grass` / `foliage` / `dry_foliage` / `water` / `hardcoded` / `none`。
- `hardcoded_colors`：纹理键 → Linear RGBA。

## 2. 加载与生效

1. Python `bridge/assets/compat.py` 读取 `configs/import_compat.json`（或 `MTK_IMPORT_COMPAT` 指定的路径）；
2. `precompile_stack` 把 JSON 传给 Rust `precompile_all_assets(resolver_overrides_json=...)`；
3. Rust 在预编译期：
   - 将 tint/hardcoded 规则合并进 `BiomeResolver`，写入 `biome/mapping`；
   - 将完整配置写入 `.mtkcache` 的 `resolver/overrides`（`COMP` chunk）；
   - 在本次预编译的模型/图集解析中立即启用 `MaterialResolver` 规则；
4. 运行时 `AssetCacheReader::open` 读取 `resolver/overrides` 并安装为当前 `MaterialResolver` 规则；
5. 没有缓存/配置时回退 Rust 内置默认规则。

## 3. 缓存刷新

`precompile_stack` 成功后会在缓存目录写入 `import_compat.sha256`。`ensure_stack_precompiled` 发现配置哈希与缓存戳不一致时会自动重新预编译，因此修改 JSON 后无需手动清缓存。

## 4. 适用场景

- 新旧 Mineways / jmc2obj 导出器的群系后缀差异；
- 模组方块缺少标准 `tintindex` 或纹理命名时的有限回退；
- 模组树叶/原木的兼容映射；
- 特定模组的 tint 分类或硬编码颜色修正。

这些规则只影响**解析与染色分类**，不会绕过原版资产门禁或生成假纹理。
