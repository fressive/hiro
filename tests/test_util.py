import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
import os
import subprocess
from server.core.util import get_data_path, bwrap_params, run_command

def test_get_data_path(tmp_path):
    # Patch DATA_PATH in the module
    with patch("server.core.util.DATA_PATH", tmp_path):
        session_id = 123
        expected_path = tmp_path / str(session_id)
        
        # Test creation
        path = get_data_path(session_id)
        assert path == expected_path
        assert path.exists()
        assert path.is_dir()
        
        # Test return existing
        path2 = get_data_path(session_id)
        assert path2 == expected_path

@patch("subprocess.run")
def test_run_command_success(mock_run):
    # Setup mock
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = b"success output"
    mock_result.stderr = b""
    mock_run.return_value = mock_result
    
    session_id = 1
    command = ["ls", "-l"]
    result = run_command(command, session_id)
    
    assert result == "success output"
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0][0] == "bwrap"
    assert args[0][-2:] == ["ls", "-l"]

@patch("subprocess.run")
def test_run_command_failure(mock_run):
    # Setup mock
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = b""
    mock_result.stderr = b"error message"
    mock_run.return_value = mock_result
    
    session_id = 1
    command = ["false"]
    result = run_command(command, session_id)
    
    assert "Command failed with exit code 1: error message" in result
    mock_run.assert_called_once()

@patch("subprocess.run")
def test_run_command_unicode_error(mock_run):
    # Setup mock
    mock_result = MagicMock()
    # Mocking stdout.decode() to raise UnicodeDecodeError
    mock_result.stdout.decode.side_effect = UnicodeDecodeError('utf-8', b'', 0, 1, 'invalid')
    mock_run.return_value = mock_result
    
    session_id = 1
    command = ["cat", "binary_file"]
    result = run_command(command, session_id)
    
    assert "command executed with binary output" in result

@patch("subprocess.run")
def test_run_command_timeout(mock_run):
    # Setup mock to raise TimeoutExpired
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["sleep", "10"], timeout=5.0)
    
    session_id = 1
    command = ["sleep", "10"]
    result = run_command(command, session_id, timeout=5.0)
    
    assert "Command timed out after 5.0 seconds" in result
    mock_run.assert_called_once()
    
def test_bwrap_sandbox(tmp_path):
    # Patch DATA_PATH in the module
    with patch("server.core.util.DATA_PATH", tmp_path):
        session_id = 123
        path = get_data_path(session_id)
        
        # The environment should contain a 'data' directory at first
        result = run_command(command=["ls"], session_id=session_id, cwd=path)
        assert "data" == result.rstrip()
        
        # 
        (path / "test").mkdir()
        result = run_command(command=["ls"], session_id=session_id, cwd=path)
        assert "test" == result.rstrip()
        
        ## Path traversal is not allowed
        result = run_command(command=["ls .."], session_id=session_id, cwd=path)
        assert "No such file or directory" in result
        
        # Test network connection
        result = run_command(command=["curl", "-s", "https://httpbin.org/get?hello=a"], session_id=session_id, cwd=path)
        assert "hello" in result