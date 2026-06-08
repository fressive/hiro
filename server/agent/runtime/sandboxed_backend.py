import subprocess
import uuid
from server.core.util import get_data_path, run_command, bwrap_params
from server.core.logger import logger
from deepagents.backends.local_shell import LocalShellBackend
from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import ExecuteResponse

class SessionSandboxedBackend(LocalShellBackend):
    """A sandboxed backend based on bwrap, with seperated data directory in session ID.
    """
    session_id = -1

    def __init__(self, session_id: int, **kwargs):
        self.session_id = session_id

        root_dir = get_data_path(session_id) / "data"
        super().__init__(
            root_dir, 
            virtual_mode=True,
            **kwargs)

    def execute(self, command, *, timeout = None):
        if not command or not isinstance(command, str):
            return ExecuteResponse(
                output="Error: Command must be a non-empty string.",
                exit_code=1,
                truncated=False,
            )

        effective_timeout = timeout if timeout is not None else self._default_timeout
        if effective_timeout <= 0:
            msg = f"timeout must be positive, got {effective_timeout}"
            raise ValueError(msg)

        try:
            # Construct the bwrap command
            full_command = [*bwrap_params(self.session_id), "bash", "-c", command]

            logger.debug("[session_id: %d] Running sandboxed command: %s", self.session_id, command)

            result = subprocess.run(
                full_command,
                check=False,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                text=True,
                timeout=effective_timeout,
                env=self._env,
                cwd=str(self.cwd),
            )

            # Process output similarly to LocalShellBackend
            output_parts = []
            if result.stdout:
                output_parts.append(result.stdout)
            if result.stderr:
                stderr_lines = result.stderr.strip().split("\n")
                output_parts.extend(f"[stderr] {line}" for line in stderr_lines)

            full_output = "\n".join(output_parts) if output_parts else "<no output>"

            # Save full output to .result directory
            result_dir = get_data_path(self.session_id) / ".result"
            result_dir.mkdir(parents=True, exist_ok=True)
            result_file = result_dir / f"output_{uuid.uuid4().hex}.txt"
            
            try:
                result_file.write_text(full_output, encoding="utf-8", errors="replace")
            except Exception as e:
                logger.error("[session_id: %d] Failed to save output to %s: %s", self.session_id, result_file, e)

            output = full_output
            # Check for truncation
            truncated = False
            if len(output) > self._max_output_bytes:
                output = output[: self._max_output_bytes]
                output += f"\n\n... Output truncated at {self._max_output_bytes} bytes."
                output += f"\nFull output saved to: {result_file.absolute()}"
                truncated = True

            # Add exit code info if non-zero
            if result.returncode != 0:
                output = f"{output.rstrip()}\n\nExit code: {result.returncode}"

            return ExecuteResponse(
                output=output,
                exit_code=result.returncode,
                truncated=truncated,
            )

        except subprocess.TimeoutExpired:
            if timeout is not None:
                msg = f"Error: Command timed out after {effective_timeout} seconds (custom timeout). The command may be stuck or require more time."
            else:
                msg = f"Error: Command timed out after {effective_timeout} seconds. For long-running commands, re-run using the timeout parameter."
            return ExecuteResponse(
                output=msg,
                exit_code=124,  # Standard timeout exit code
                truncated=False,
            )
        except Exception as e: 
            return ExecuteResponse(
                output=f"Error executing command ({type(e).__name__}): {e}",
                exit_code=1,
                truncated=False,
            )