# PBR legacy-vs-baked 视觉回归记录

> 日期：2026-10-21
> 基线：`MoziToolKit@aa7fcbe`、`libmozitoolkit@df06886`
> 工具：[`tools/validate_pbr_visual_regression.py`](../../tools/validate_pbr_visual_regression.py)
> 相关：[PBR 通道规范](pbr_channel_spec.md)

## 目的

在删除 `LabPBR 1.3 Decoder` 之前，用旧解码器作为 oracle，确认 Rust 预编译的
`MtkPackedV1` 通道 + 标准 Principled 图在真实 LabPBR 资源上视觉等价。

## 环境与场景

- Blender **5.2.1 LTS**，EEVEE Next，512×512，32 samples。
- 资源栈：`26.2-Fabric.jar`（vanilla base）+ `SPBR-21.zip`（LabPBR）。
- 场景：2×2 平面，正交相机，单盏 Area Light；背景 0.04。
- Legacy 材质：raw `_n` / `_s` + `LabPBR 1.3 Decoder`，平面 UV = `[0,1]`。
- Baked 材质：Rust 产出的 `_n` / `_orm` / `_aux` + `build_pbr_shading`，
  平面 UV = atlas sprite 的 `uv_bounds`。
- 两者使用相同的相机、灯光、色彩空间与 `Closest` 采样。

## 结果

| Block | 类型 | MAE | RMSE | PSNR | 中心裁剪 MAE |
| :--- | :--- | ---: | ---: | ---: | ---: |
| `stone` | 电介质 / 低 F0 | 0.000009 | 0.000191 | **74.39 dB** | 0.000014 |
| `gold_block` | 金属 / 高 F0 | 0.000183 | 0.000943 | **60.51 dB** | 0.000199 |
| `oak_planks` | 电介质 / 少量 SSS | 0.000039 | 0.000390 | **68.18 dB** | 0.000055 |

阈值：`MTK_VISUAL_PSNR_MIN=40 dB`。全部 **PASS**。

## 解读

- 差异处于 8-bit 量化级别：normal Z 重建、F0→IOR 的 8-bit 编码、emission
  `/254` 与旧实现 `/255` 的 0.4% 差异。
- `gold_block` 的差异最大（60.5 dB），但中心区域 MAE 仍只有 0.0002；
  旧解码器对金属也会从 F0 反解一个很高的 IOR，而 baked 通道按规范固定为 1.5。
  在这个 Principled + metallic=1 的场景中两者渲染结果仍高度一致，说明该差异
  不构成可见回归。
- 该结果只覆盖静态、无 tint、无动画、无 transmission/thin-wall 的 PBR 通道；
  biome tint、动画和游戏语义属于独立路径，不在本对比范围内。

## 复跑

```bash
cd MoziToolKit
SITE="$("../libmozitoolkit/.venv/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
BLENDER_USER_CONFIG="$PWD/.blender-test-config" PYTHONPATH="$SITE" \
  blender --background --factory-startup --python tools/validate_pbr_visual_regression.py
```

可选环境变量：

- `MTK_VISUAL_VANILLA_JAR`（默认 `../26.2-Fabric.jar`）
- `MTK_VISUAL_RESOURCE_PACK`（默认 `../SPBR-21.zip` 或 `~/Downloads/SPBR-21.zip`）
- `MTK_VISUAL_BLOCKS`（默认 `stone,gold_block,oak_planks`）
- `MTK_VISUAL_PSNR_MIN`（默认 `40`）
- `MTK_VISUAL_OUTPUT`（默认新建临时目录；渲染图保留在该目录）

> 注意：harness 会显式把 legacy 平面的 UV 重置为 `[0,1]`，避免上一轮 baked
> 的 sprite UV 残留；这是早期临时脚本里出现过的一个测量误差。
