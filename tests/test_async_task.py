"""
Unit tests for AsyncTask and ModalTaskRunner asynchronous non-blocking worker pipeline.
"""

import queue
import time
from types import SimpleNamespace

import pytest

from MoziToolKit.bridge.progress import ProgressReport
from MoziToolKit.utils.async_task import AsyncTask, ModalTaskRunner


def dummy_heavy_worker(count: int, progress_callback=None):
    """Simulates a heavy calculation that emits progress reports."""
    for i in range(1, count + 1):
        if progress_callback:
            progress_callback(ProgressReport(current=i, total=count, message=f"Step {i}"))
        time.sleep(0.005)
    return {"calculated": count * 10}


def dummy_failing_worker(progress_callback=None):
    """Simulates a failing worker."""
    if progress_callback:
        progress_callback(ProgressReport(current=1, total=10, message="Starting"))
    raise ValueError("Calculation overflow simulated")


class TestAsyncTask:
    def test_async_task_success(self):
        task = AsyncTask(target=dummy_heavy_worker, args=(5,))
        task.start()

        # Wait until done
        max_wait = 2.0
        start = time.time()
        while not task.is_done and time.time() - start < max_wait:
            time.sleep(0.01)

        assert task.is_done is True
        assert task.error is None
        assert task.result == {"calculated": 50}

        # Verify progress queue collected reports
        reports = []
        while not task.queue.empty():
            kind, payload = task.queue.get_nowait()
            if kind == "PROGRESS":
                reports.append(payload)

        assert len(reports) == 5
        assert reports[-1].current == 5
        assert reports[-1].total == 5

    def test_async_task_error(self):
        task = AsyncTask(target=dummy_failing_worker)
        task.start()

        max_wait = 2.0
        start = time.time()
        while not task.is_done and time.time() - start < max_wait:
            time.sleep(0.01)

        assert task.is_done is True
        assert task.error is not None
        assert "Calculation overflow" in str(task.error)

    def test_async_task_sync_run(self):
        task = AsyncTask(target=dummy_heavy_worker, args=(3,))
        res = task.run_sync()
        assert res == {"calculated": 30}
        assert task.is_done is True
        assert task.error is None


class TestModalTaskRunner:
    def test_modal_task_runner_sync_fallback(self):
        mock_op = SimpleNamespace(report=lambda *args: None)
        mock_ctx = SimpleNamespace(window=None)

        success_called = []

        def on_success(res):
            success_called.append(res)

        task = AsyncTask(target=dummy_heavy_worker, args=(3,))
        runner = ModalTaskRunner(
            operator=mock_op,
            context=mock_ctx,
            task=task,
            on_success=on_success,
        )

        ret = runner.start()
        assert ret == {"FINISHED"}
        assert len(success_called) == 1
        assert success_called[0] == {"calculated": 30}

    def test_modal_task_runner_modal_flow(self):
        wm_calls = []
        mock_wm = SimpleNamespace(
            event_timer_add=lambda *args, **kwargs: (wm_calls.append("event_timer_add"), object())[1],
            event_timer_remove=lambda *args, **kwargs: wm_calls.append("event_timer_remove"),
            modal_handler_add=lambda *args, **kwargs: wm_calls.append("modal_handler_add"),
        )
        mock_op = SimpleNamespace(report=lambda *args: None)
        mock_ctx = SimpleNamespace(
            window_manager=mock_wm,
            window=object(),
        )

        reporter_calls = []
        reporter = SimpleNamespace(
            start=lambda: reporter_calls.append("start"),
            update=lambda *args, **kwargs: reporter_calls.append("update"),
            on_progress=lambda *args, **kwargs: reporter_calls.append("on_progress"),
            close=lambda: reporter_calls.append("close"),
        )
        success_called = []

        def on_success(res):
            success_called.append(res)

        task = AsyncTask(target=dummy_heavy_worker, args=(2,))
        runner = ModalTaskRunner(
            operator=mock_op,
            context=mock_ctx,
            task=task,
            reporter=reporter,
            on_success=on_success,
            force_modal=True,
        )

        ret = runner.start()
        assert ret == {"RUNNING_MODAL"}
        assert "start" in reporter_calls
        assert "event_timer_add" in wm_calls
        assert "modal_handler_add" in wm_calls

        # Wait for task thread to finish
        max_wait = 2.0
        start = time.time()
        while not task.is_done and time.time() - start < max_wait:
            time.sleep(0.01)

        # Simulate timer event
        timer_event = SimpleNamespace(type="TIMER")

        modal_ret = runner.modal(timer_event)
        assert modal_ret == {"FINISHED"}
        assert len(success_called) == 1
        assert success_called[0] == {"calculated": 20}
        assert "close" in reporter_calls
        assert "event_timer_remove" in wm_calls
