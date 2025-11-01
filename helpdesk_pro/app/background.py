from __future__ import annotations

import atexit
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from flask import current_app

_executor_lock = threading.Lock()
_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is not None:
        return _executor

    with _executor_lock:
        if _executor is None:
            _executor = ThreadPoolExecutor(
                max_workers=4,
                thread_name_prefix="helpdesk-bg",
            )
            atexit.register(_executor.shutdown, wait=False)
    return _executor


def submit_background_task(
    func: Callable[..., Any],
    *args: Any,
    description: str | None = None,
    **kwargs: Any,
) -> Future[Any]:
    """
    Run ``func`` in a thread pool while preserving the Flask app context.

    :param func: callable to execute.
    :param description: log-friendly description if the task raises.
    :return: the Future representing the scheduled work.
    """
    app = current_app._get_current_object()
    task_description = description or getattr(func, "__name__", "background task")

    def runner() -> Any:
        with app.app_context():
            try:
                return func(*args, **kwargs)
            except Exception:
                app.logger.exception("Background task failed: %s", task_description)
                raise

    executor = _get_executor()
    return executor.submit(runner)
