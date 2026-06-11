import subprocess
import os
from .logger import logger
from pathlib import Path

DATA_PATH = Path("./data")
NUCLEI_TEMPLATES_DIRNAME = "nuclei-templates"
    
def get_data_path(session_id: int) -> Path:
    """Get session path with specified session ID. The directory will be created if the path is not existed.
    
    Args:
        session_id: The session ID, which should be retrived from a SessionContext.
        
    Returns:
        A Path object with path "DATA_PATH/{session_id}".
    """
    
    path = DATA_PATH / str(session_id)
    if not path.exists():
        logger.debug("Creating directory %s", str(path))
        path.mkdir(parents=True)
        
        path_data = DATA_PATH / str(session_id) / "data"
        path_data.mkdir(parents=True)
        
    return path
            

def bwrap_params(session_id: int):
    """
    Return the params of bwrap sandbox.
    
    Restrictions:
        1. Readonly binds: 
            /usr -> /usr
            /lib -> /lib
            /lib64 -> /lib64
            /bin -> /bin
            /etc -> /etc        
            ~/nuclei-templates -> ~/nuclei-templates, when present
            
            !!!Warning!!!: The /etc directory is readable in the sandbox, some sensitive data may suffer risk of leakage.
            
        2. Read/Write binds:
            ./ -> /data/{session_id}
            Note that the command should be executed in the data directory (use `cwd` argument of subprocess.run).
            
        3. Create /tmp, /proc, /dev
        
        4. Disable permissions except for network
        
        5. Chdir to /home
        
        6. Kill the process when the Hiro server exits
    
    """
    ro_binds = {
        "/usr": "/usr",
        "/lib": "/lib",
        "/lib64": "/lib64",
        "/bin": "/bin",
        "/etc": "/etc"
    }
    
    data_path = get_data_path(session_id)
    
    binds = {
        str(data_path.absolute()): "/data"
    }

    nuclei_templates_path = _get_nuclei_templates_path()
    extra_dirs = (
        _sandbox_parent_dirs(nuclei_templates_path)
        if nuclei_templates_path.is_dir()
        else []
    )
    extra_ro_binds = _nuclei_templates_ro_binds(nuclei_templates_path)
    sandbox_dirs = _unique_paths(["/tmp", *extra_dirs])
    
    return [
        "bwrap",
        *[item for sublist in [["--ro-bind", k, v] for k, v in ro_binds.items()] for item in sublist],
        *[item for sublist in [["--dir", path] for path in sandbox_dirs] for item in sublist],
        *[item for sublist in [["--ro-bind", k, v] for k, v in extra_ro_binds.items()] for item in sublist],
        *[item for sublist in [["--bind", k, v] for k, v in binds.items()] for item in sublist],
        "--proc", "/proc",
        "--dev", "/dev",
        "--chdir", "/data",
        "--unshare-all",
        "--share-net",
        "--die-with-parent",
    ]


def _get_nuclei_templates_path() -> Path:
    home = Path(os.path.expanduser("~"))
    return home / NUCLEI_TEMPLATES_DIRNAME


def _nuclei_templates_ro_binds(templates_path: Path) -> dict[str, str]:
    if not templates_path.is_dir():
        return {}
    absolute_path = str(templates_path.absolute())
    return {absolute_path: absolute_path}


def _sandbox_parent_dirs(path: Path) -> list[str]:
    if not path.is_absolute():
        path = path.absolute()

    parents = []
    for parent in reversed(path.parents):
        if str(parent) == "/":
            continue
        parents.append(str(parent))
    return parents


def _unique_paths(paths: list[str]) -> list[str]:
    unique = []
    seen = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def run_command(
    command: str | list[str],
    session_id: int,
    timeout: float = None,
    cwd: str = None,
) -> str:
    """Run a command with bwrap.
    
    """
    try:
        if isinstance(command, list):
            full_command = [*bwrap_params(session_id), *command]
        else:
            full_command = [*bwrap_params(session_id), "bash", "-c", command]
        
        logger.debug("[session_id: %d] Running command: %s (cwd: %s)", session_id, " ".join(full_command), cwd)
        
        result = subprocess.run(
            full_command,
            timeout=timeout,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            cwd=cwd
        )
        
        stdout = result.stdout.decode()
        stderr = result.stderr.decode('utf-8', errors='ignore')
        
        if result.returncode != 0:
            error_msg = f"Command failed with exit code {result.returncode}: {stderr}"
            logger.error("[session_id: %d] %s", session_id, error_msg)
            return error_msg
        else:
            logger.debug("[session_id: %d] Finished running command.", session_id)
            return stdout
    except subprocess.TimeoutExpired:
        error_msg = f"Command timed out after {timeout} seconds"
        logger.error("[session_id: %d] %s", session_id, error_msg)
        return error_msg
    except UnicodeDecodeError as e:
        return "command executed with binary output"
    except Exception as e:
        return f"command failed with exception {e}"
