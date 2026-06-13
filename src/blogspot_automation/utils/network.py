from __future__ import annotations

from dataclasses import dataclass
from http.client import HTTPConnection, HTTPSConnection
import json
import logging
import socket
import time
from typing import Any
from urllib.parse import urlsplit


RETRY_BACKOFF_SECONDS = (2, 5, 10)


@dataclass(slots=True)
class HTTPRequestError(RuntimeError):
    message: str
    error_class: str
    retry_count: int
    connect_timeout: int
    read_timeout: int
    status_code: int | None = None

    def __str__(self) -> str:
        return self.message

    @property
    def is_timeout(self) -> bool:
        return "timeout" in self.error_class.lower()


def post_json_with_retry(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    logger: logging.Logger,
    operation_name: str,
    method: str = "POST",
    connect_timeout: int = 20,
    read_timeout: int = 180,
    backoff_seconds: tuple[int, ...] = RETRY_BACKOFF_SECONDS,
) -> str:
    request_body = None if payload is None else json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None
    total_attempts = len(backoff_seconds) + 1

    for attempt in range(1, total_attempts + 1):
        try:
            return _post_json_once(
                url=url,
                headers=headers,
                payload=request_body,
                method=method,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            should_retry = _should_retry(exc)
            if attempt >= total_attempts or not should_retry:
                break
            logger.warning(
                "%s failed on attempt %s/%s: %s",
                operation_name,
                attempt,
                total_attempts,
                exc,
            )
            time.sleep(backoff_seconds[attempt - 1])

    if isinstance(last_error, HTTPRequestError):
        raise last_error
    if last_error is None:
        raise RuntimeError(f"{operation_name} failed without an exception.")
    raise HTTPRequestError(
        message=str(last_error),
        error_class=type(last_error).__name__,
        retry_count=max(total_attempts - 1, 0),
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
    ) from last_error


def _post_json_once(
    *,
    url: str,
    headers: dict[str, str],
    payload: bytes | None,
    method: str,
    connect_timeout: int,
    read_timeout: int,
) -> str:
    parts = urlsplit(url)
    connection_cls = HTTPSConnection if parts.scheme == "https" else HTTPConnection
    connection = connection_cls(parts.hostname, parts.port, timeout=connect_timeout)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    try:
        connection.connect()
        if connection.sock is not None:
            connection.sock.settimeout(read_timeout)
        connection.request(method.upper(), path, body=payload, headers=headers)
        response = connection.getresponse()
        body = response.read().decode("utf-8", errors="replace")
        if 500 <= response.status <= 599:
            raise HTTPRequestError(
                message=f"HTTP {response.status}: {body}",
                error_class="HTTP5xxError",
                retry_count=0,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                status_code=response.status,
            )
        if response.status >= 400:
            raise HTTPRequestError(
                message=f"HTTP {response.status}: {body}",
                error_class="HTTPError",
                retry_count=0,
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                status_code=response.status,
            )
        return body
    except TimeoutError as exc:
        raise HTTPRequestError(
            message=f"The read operation timed out: {exc}",
            error_class=type(exc).__name__,
            retry_count=0,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        ) from exc
    except socket.timeout as exc:
        raise HTTPRequestError(
            message=f"The read operation timed out: {exc}",
            error_class=type(exc).__name__,
            retry_count=0,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        ) from exc
    except ConnectionResetError as exc:
        raise HTTPRequestError(
            message=str(exc),
            error_class=type(exc).__name__,
            retry_count=0,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        ) from exc
    finally:
        connection.close()


def _should_retry(exc: Exception) -> bool:
    if isinstance(exc, HTTPRequestError):
        if exc.error_class in {"HTTP5xxError", "TimeoutError", "timeout", "socket.timeout", "ConnectionResetError"}:
            return True
        return exc.status_code is not None and 500 <= exc.status_code <= 599
    return isinstance(exc, (TimeoutError, socket.timeout, ConnectionResetError))
