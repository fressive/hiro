import pytest
import subprocess
import uuid
from unittest.mock import MagicMock, patch
from server.agent.runtime.sandboxed_backend import SessionSandboxedBackend
from deepagents.backends.protocol import ExecuteResponse

@pytest.fixture
def backend():
    return SessionSandboxedBackend(session_id=123)

def test_execute_success(backend):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["bwrap", "bash", "-c", "echo hello"],
            returncode=0,
            stdout="hello\n",
            stderr=""
        )
        
        response = backend.execute("echo hello")
        
        assert response.output == "hello\n"
        assert response.exit_code == 0
        assert response.truncated is False
        mock_run.assert_called_once()

def test_execute_error(backend):
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["bwrap", "bash", "-c", "ls non_existent"],
            returncode=2,
            stdout="",
            stderr="ls: cannot access 'non_existent': No such file or directory\n"
        )
        
        response = backend.execute("ls non_existent")
        
        assert "[stderr] ls: cannot access 'non_existent': No such file or directory" in response.output
        assert "Exit code: 2" in response.output
        assert response.exit_code == 2
        assert response.truncated is False

def test_execute_timeout(backend):
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd=["bwrap"], timeout=1)
        
        response = backend.execute("sleep 10", timeout=1)
        
        assert "Error: Command timed out after 1 seconds" in response.output
        assert response.exit_code == 124

def test_execute_truncation(backend):
    with patch("subprocess.run") as mock_run:
        # Mocking a very long output
        mock_run.return_value = subprocess.CompletedProcess(
            args=["bwrap", "bash", "-c", "cat huge_file"],
            returncode=0,
            stdout="A" * 2000,
            stderr=""
        )
        
        # We need to access _max_output_bytes, which is inherited from LocalShellBackend
        backend._max_output_bytes = 1000
        
        response = backend.execute("cat huge_file")
        
        assert len(response.output) > 1000
        assert "... Output truncated at 1000 bytes." in response.output
        assert response.truncated is True
        assert response.output.startswith("A" * 1000)
        assert "Full output saved to:" in response.output
        
        # Verify the file was created and contains full output
        import re
        match = re.search(r"Full output saved to: (.*\.txt)", response.output)
        assert match is not None
        file_path = match.group(1)
        import os
        assert os.path.exists(file_path)
        with open(file_path, "r") as f:
            assert f.read() == "A" * 2000

def test_execute_invalid_command(backend):
    response = backend.execute(None)
    assert "Error: Command must be a non-empty string." in response.output
    assert response.exit_code == 1
