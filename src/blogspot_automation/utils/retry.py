from __future__ import annotations

import logging
import time
from typing import Callable, TypeVar


T = TypeVar("T")


def retry_call(
    *,
    operation: Callable[[], T],
    attempts: int,
    delay_seconds: float,
    operation_name: str,
    logger: logging.Logger,
) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= attempts:
                break
            logger.warning(
                "%s failed on attempt %s/%s: %s",
                operation_name,
                attempt,
                attempts,
                exc,
            )
            time.sleep(delay_seconds)
    assert last_error is not None
    raise last_error
