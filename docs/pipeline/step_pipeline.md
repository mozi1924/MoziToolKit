# 模块七：异步任务与进度调度 (Async Tasks & Progress)

> 旧版 `pipeline/` 微内核（`PipelineStep` / `PipelineContext` / `presets/`）已在 v2.0 重构中移除。
> 当前 MoziToolKit 的耗时操作统一使用 [`utils/async_task.py`](../../utils/async_task.py) 的
> `AsyncTask` / `ModalTaskRunner`，并由资产门禁与进度回调驱动。

## 1. 当前职责边界

- **`AsyncTask`**：定义后台任务的可调用体、取消标志与进度回调；
- **`ModalTaskRunner`**：在 Blender 主线程以 `wm.event_timer_add` 步进执行任务，
  不阻塞 UI，并可被 `ESC`/取消操作中断；
- **`utils/progress.py` / `set_progress`**：把 Rust `ProgressReport` 或 Python
  阶段进度统一映射到 Blender 状态栏与 `wm.progress_*`；
- **`bridge/assets/guard.py`**：在执行资产相关任务前校验 `.mtkcache` 是否就绪，
  必要时先走预编译门禁。

## 2. 典型调用链

```text
Operator.execute()
  └─ run_task_with_asset_guard(...)
       ├─ check_asset_cache_status / precompile
       └─ ModalTaskRunner(AsyncTask(...)).start()
            ├─ modal(): 分片执行 + 更新进度
            ├─ cancel(): 设置取消标志
            └─ finish(): 提交结果 / 关闭进度报告
```

相关入口：

- [`utils/async_task.py`](../../utils/async_task.py)
- [`utils/progress.py`](../../utils/progress.py)
- [`bridge/assets/guard.py`](../../bridge/assets/guard.py)
- [`operators/op_precompile.py`](../../operators/op_precompile.py)
- [`operators/sync/op_sync_rebuild.py`](../../operators/sync/op_sync_rebuild.py)

## 3. 不变量

1. 耗时几何/纹理/网络计算必须在 Rust 中完成，Python 任务只做调度与 Blender 对象注入；
2. 任务取消必须及时释放定时器、进度报告与临时缓冲；
3. 进度更新不得回退，阶段切换需保持单调；
4. 资产未就绪时不得进入几何构建，必须先经过预编译门禁。
