from server.core.util import get_data_path, run_command
from server.core.logger import logger
from deepagents.backends.local_shell import LocalShellBackend
from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import ExecuteResponse

class SessionSandboxedBackend(LocalShellBackend):
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
            output = run_command(command, self.session_id, timeout=timeout, cwd=get_data_path(self.session_id))
            
            return ExecuteResponse(
                output=output,
                exit_code=0,
                truncated=False,
            )
        except Exception as e: 
            return ExecuteResponse(
                output=f"Error executing command ({type(e).__name__}): {e}",
                exit_code=1,
                truncated=False,
            )