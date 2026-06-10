"""Nuclei automatic fingerprinting tool."""

from __future__ import annotations

from typing import Any

from langchain.tools import ToolRuntime, tool

from server.agent.runtime.context import SessionContext
from server.core.util import get_data_path, run_command


MAX_TIMEOUT_SECONDS = 900
DEFAULT_TIMEOUT_SECONDS = 180
MAX_OUTPUT_CHARS = 20000
DEFAULT_RATE_LIMIT = 10
MAX_RATE_LIMIT = 100
DEFAULT_RETRIES = 1
MAX_RETRIES = 3

NUCLEI_FINGERPRINT_DESCRIPTION = (
    "Run nuclei automatic scan (-as) against an authorized HTTP or HTTPS target "
    "to fingerprint technologies and surface relevant low-noise nuclei matches. "
    "Use only for in-scope targets from the current session."
)


def run_nuclei_fingerprint_scan(
    *,
    session_id: int,
    target_url: str,
    headers: dict[str, str] | None = None,
    rate_limit: int = DEFAULT_RATE_LIMIT,
    retries: int = DEFAULT_RETRIES,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Run nuclei -as inside the session sandbox and return compact output."""
    target = target_url.strip()
    if not target.startswith(("http://", "https://")):
        return "Error: target_url must start with http:// or https://"

    normalized_timeout = min(
        max(1, int(timeout_seconds or DEFAULT_TIMEOUT_SECONDS)),
        MAX_TIMEOUT_SECONDS,
    )
    normalized_rate_limit = min(
        max(1, int(rate_limit or DEFAULT_RATE_LIMIT)),
        MAX_RATE_LIMIT,
    )
    normalized_retries = min(
        max(0, int(retries if retries is not None else DEFAULT_RETRIES)),
        MAX_RETRIES,
    )

    command = [
        "nuclei",
        "-u",
        target,
        "-as",
        "-silent",
        "-nc",
        "-duc",
        "-rl",
        str(normalized_rate_limit),
        "-retries",
        str(normalized_retries),
    ]

    try:
        for name, value in _normalize_headers(headers):
            command.extend(["-H", f"{name}: {value}"])
    except ValueError as exc:
        return f"Error: {exc}"

    output = run_command(
        command,
        session_id=session_id,
        timeout=normalized_timeout,
        cwd=get_data_path(session_id),
    )
    text = _truncate_output(output)
    return text if text.strip() else "No nuclei automatic-scan findings were produced."


@tool("nuclei_fingerprint", description=NUCLEI_FINGERPRINT_DESCRIPTION)
async def nuclei_fingerprint(
    target_url: str,
    runtime: ToolRuntime[SessionContext],
    headers: dict[str, str] | None = None,
    rate_limit: int = DEFAULT_RATE_LIMIT,
    retries: int = DEFAULT_RETRIES,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    return run_nuclei_fingerprint_scan(
        session_id=runtime.context.session_id,
        target_url=target_url,
        headers=headers,
        rate_limit=rate_limit,
        retries=retries,
        timeout_seconds=timeout_seconds,
    )


def _normalize_headers(headers: dict[str, str] | None) -> list[tuple[str, str]]:
    if not headers:
        return []

    normalized_headers = []
    for raw_name, raw_value in headers.items():
        name = str(raw_name).strip()
        value = str(raw_value).strip()
        if not name:
            raise ValueError("header names must not be empty")
        if ":" in name:
            raise ValueError("header names must not contain ':'")
        if any(char in name or char in value for char in ("\r", "\n")):
            raise ValueError("headers must not contain newlines")
        normalized_headers.append((name, value))
    return normalized_headers


def _truncate_output(output: Any) -> str:
    text = str(output)
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return (
        text[:MAX_OUTPUT_CHARS]
        + f"\n...[truncated {len(text) - MAX_OUTPUT_CHARS} chars]"
    )
