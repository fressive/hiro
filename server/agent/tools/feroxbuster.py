"""Feroxbuster web content discovery tool."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from langchain.tools import ToolRuntime, tool

from server.agent.runtime.context import SessionContext
from server.core.util import get_data_path, run_command


MAX_TIMEOUT_SECONDS = 3600
DEFAULT_TIMEOUT_SECONDS = 1800
MAX_OUTPUT_CHARS = 20000
DEFAULT_THREADS = 10
DEFAULT_DEPTH = 2

FEROXBUSTER_DESCRIPTION = (
    "Run feroxbuster against an authorized HTTP or HTTPS target to discover "
    "web paths and directories. Use only for in-scope targets from the current "
    "session."
)


def run_feroxbuster_scan(
    *,
    session_id: int,
    target_url: str,
    wordlist: str | None = None,
    extensions: str | None = None,
    depth: int = DEFAULT_DEPTH,
    threads: int = DEFAULT_THREADS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    follow_redirects: bool = True,
    insecure: bool = True,
) -> str:
    """Run feroxbuster inside the session sandbox and return compact output."""
    target = target_url.strip()
    if not target.startswith(("http://", "https://")):
        return "Error: target_url must start with http:// or https://"

    normalized_timeout = min(
        max(1, int(timeout_seconds or DEFAULT_TIMEOUT_SECONDS)),
        MAX_TIMEOUT_SECONDS,
    )
    normalized_depth = max(0, min(int(depth or DEFAULT_DEPTH), 5))
    normalized_threads = max(1, min(int(threads or DEFAULT_THREADS), 50))

    command = [
        "feroxbuster",
        "-u",
        target,
        "--no-state",
        "--silent",
        "--depth",
        str(normalized_depth),
        "--threads",
        str(normalized_threads),
    ]

    if follow_redirects:
        command.append("--redirects")
    if insecure:
        command.append("--insecure")
    if wordlist:
        command.extend(["--wordlist", _normalize_wordlist(wordlist)])
    if extensions:
        extension_values = [
            extension.strip().lstrip(".")
            for extension in extensions.split(",")
            if extension.strip()
        ]
        if extension_values:
            command.extend(["--extensions", ",".join(extension_values)])

    output = run_command(
        command,
        session_id=session_id,
        timeout=normalized_timeout,
        cwd=get_data_path(session_id),
    )
    return _truncate_output(output)


@tool("feroxbuster", description=FEROXBUSTER_DESCRIPTION)
async def feroxbuster(
    target_url: str,
    runtime: ToolRuntime[SessionContext],
    wordlist: str | None = None,
    extensions: str | None = None,
    depth: int = DEFAULT_DEPTH,
    threads: int = DEFAULT_THREADS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    follow_redirects: bool = True,
    insecure: bool = True,
) -> str:
    return run_feroxbuster_scan(
        session_id=runtime.context.session_id,
        target_url=target_url,
        wordlist=wordlist,
        extensions=extensions,
        depth=depth,
        threads=threads,
        timeout_seconds=timeout_seconds,
        follow_redirects=follow_redirects,
        insecure=insecure,
    )


def _normalize_wordlist(wordlist: str) -> str:
    value = wordlist.strip()
    if not value:
        return value
    if value.startswith("/"):
        return value
    normalized = PurePosixPath(value)
    if any(part == ".." for part in normalized.parts):
        raise ValueError("wordlist must not contain parent directory traversal")
    return str(normalized)


def _truncate_output(output: Any) -> str:
    text = str(output)
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return (
        text[:MAX_OUTPUT_CHARS]
        + f"\n...[truncated {len(text) - MAX_OUTPUT_CHARS} chars]"
    )
