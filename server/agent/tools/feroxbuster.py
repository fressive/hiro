"""Feroxbuster web content discovery tool."""

from __future__ import annotations

import time
from pathlib import Path, PurePosixPath
from typing import Any

from langchain.tools import ToolRuntime, tool

from server.agent.runtime.context import SessionContext
from server.core.util import get_data_path, run_command


MAX_TIMEOUT_SECONDS = 3600
DEFAULT_TIMEOUT_SECONDS = 1800
MAX_OUTPUT_CHARS = 20000
DEFAULT_THREADS = 10
DEFAULT_DEPTH = 2
COMMAND_TIMEOUT_GRACE_SECONDS = 15
CHECKPOINT_DIR = PurePosixPath("data/feroxbuster-checkpoints")

FEROXBUSTER_DESCRIPTION = (
    "Run feroxbuster against an authorized HTTP or HTTPS target to discover "
    "web paths and directories. Checkpointing is enabled by default; when a "
    "scan times out, resume with resume_from_checkpoint and a larger timeout. "
    "Use only for in-scope targets from the current session."
)


def run_feroxbuster_scan(
    *,
    session_id: int,
    target_url: str | None = None,
    wordlist: str | None = None,
    extensions: str | None = None,
    depth: int = DEFAULT_DEPTH,
    threads: int = DEFAULT_THREADS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    follow_redirects: bool = True,
    insecure: bool = True,
    checkpoint_enabled: bool = True,
    resume_from_checkpoint: str | None = None,
) -> str:
    """Run feroxbuster inside the session sandbox and return compact output."""
    target = (target_url or "").strip()
    if not resume_from_checkpoint and not target.startswith(("http://", "https://")):
        return "Error: target_url must start with http:// or https://"

    normalized_timeout = min(
        max(1, int(timeout_seconds or DEFAULT_TIMEOUT_SECONDS)),
        MAX_TIMEOUT_SECONDS,
    )
    normalized_depth = max(0, min(int(depth or DEFAULT_DEPTH), 5))
    normalized_threads = max(1, min(int(threads or DEFAULT_THREADS), 50))

    session_path = get_data_path(session_id)
    start_time = time.time()

    if resume_from_checkpoint:
        try:
            checkpoint_path = _normalize_checkpoint(
                resume_from_checkpoint,
                session_path=session_path,
            )
        except ValueError as exc:
            return f"Error: {exc}"
        command = [
            "feroxbuster",
            "--resume-from",
            checkpoint_path,
            "--silent",
            "--time-limit",
            f"{normalized_timeout}s",
        ]
    else:
        command = [
            "feroxbuster",
            "-u",
            target,
            "--silent",
            "--depth",
            str(normalized_depth),
            "--threads",
            str(normalized_threads),
            "--time-limit",
            f"{normalized_timeout}s",
        ]

        if not checkpoint_enabled:
            command.append("--no-state")

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

    outer_timeout = normalized_timeout + COMMAND_TIMEOUT_GRACE_SECONDS

    output = run_command(
        command,
        session_id=session_id,
        timeout=outer_timeout,
        cwd=session_path,
    )
    checkpoint_files = (
        _collect_checkpoint_files(session_path=session_path, start_time=start_time)
        if checkpoint_enabled
        else []
    )
    return _format_output(output, checkpoint_files)


@tool("feroxbuster", description=FEROXBUSTER_DESCRIPTION)
async def feroxbuster(
    runtime: ToolRuntime[SessionContext],
    target_url: str | None = None,
    wordlist: str | None = None,
    extensions: str | None = None,
    depth: int = DEFAULT_DEPTH,
    threads: int = DEFAULT_THREADS,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    follow_redirects: bool = True,
    insecure: bool = True,
    checkpoint_enabled: bool = True,
    resume_from_checkpoint: str | None = None,
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
        checkpoint_enabled=checkpoint_enabled,
        resume_from_checkpoint=resume_from_checkpoint,
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


def _normalize_checkpoint(checkpoint: str, *, session_path) -> str:
    value = checkpoint.strip()
    if not value:
        raise ValueError("resume_from_checkpoint must not be empty")

    session_root = session_path.resolve()
    path = PurePosixPath(value)
    if path.is_absolute():
        resolved = Path(value).resolve()
        try:
            return resolved.relative_to(session_root).as_posix()
        except ValueError as exc:
            raise ValueError(
                "resume_from_checkpoint must be inside the session directory"
            ) from exc

    if any(part == ".." for part in path.parts):
        raise ValueError("resume_from_checkpoint must not contain parent traversal")
    return str(path)


def _collect_checkpoint_files(*, session_path, start_time: float) -> list[str]:
    checkpoint_dir = session_path / CHECKPOINT_DIR.as_posix()
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_files: list[str] = []
    for state_file in sorted(session_path.glob("*.state")):
        try:
            if state_file.stat().st_mtime + 1 < start_time:
                continue
            destination = checkpoint_dir / state_file.name
            state_file.replace(destination)
            checkpoint_files.append(_session_relative_path(destination, session_path))
        except OSError:
            continue
    return checkpoint_files


def _session_relative_path(path, session_path) -> str:
    return Path(path).resolve().relative_to(session_path.resolve()).as_posix()


def _format_output(output: Any, checkpoint_files: list[str]) -> str:
    text = _truncate_output(output)
    if not checkpoint_files:
        return text

    checkpoint_lines = "\n".join(f"- {path}" for path in checkpoint_files)
    checkpoint_note = (
        "\n\nCheckpoint files:\n"
        f"{checkpoint_lines}\n"
        "Resume an incomplete scan with resume_from_checkpoint set to one of "
        "these paths and a larger timeout_seconds value."
    )
    return _truncate_output(f"{text}{checkpoint_note}")


def _truncate_output(output: Any) -> str:
    text = str(output)
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return (
        text[:MAX_OUTPUT_CHARS]
        + f"\n...[truncated {len(text) - MAX_OUTPUT_CHARS} chars]"
    )
