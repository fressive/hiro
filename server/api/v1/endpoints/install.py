"""Installation endpoints."""

import os
import sys
import time
import subprocess
import shutil

from fastapi import APIRouter, BackgroundTasks, HTTPException

from server.core.installation import (
    get_installation_status,
    initialize_application_installation,
    is_application_installed,
    verify_database_connection,
)
from server.schemas.installation import (
    InstallationRequest,
    InstallationResponse,
    InstallationStatusResponse,
    DatabaseCheckRequest,
    DatabaseCheckResponse,
    SystemCheckResponse,
    SystemCheckItem,
)


router = APIRouter()


def _restart_process() -> None:
    time.sleep(0.5)
    os.execv(sys.executable, [sys.executable, *sys.argv])


@router.get("/status", response_model=InstallationStatusResponse)
async def install_status():
    """Return the current installation status."""

    return get_installation_status()


@router.post("/check-db", response_model=DatabaseCheckResponse)
async def check_db_connection(payload: DatabaseCheckRequest):
    """Verify the database connection."""

    success, message = await verify_database_connection(payload.database_url)
    return DatabaseCheckResponse(success=success, message=message)


@router.get("/check-system", response_model=SystemCheckResponse)
async def check_system_requirements():
    """Check if required system programs are installed and executable."""

    programs = {
        "wget": ["--version"], 
        "curl": ["--version"],
        "bwrap": ["--version"],
        "feroxbuster": ["--version"]
    }
    items = []
    overall_success = True

    for prog, params in programs.items():
        try:
            # Check if the command exists and can be executed
            result = subprocess.run(
                [prog, *params],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=2
            )
            
            if result.returncode == 0:
                # Successfully executed, extract the first line of version info
                version_info = result.stdout.split('\n')[0] if result.stdout else "Available"
                items.append(SystemCheckItem(name=prog, exists=True, message=version_info))
            else:
                # Command exists but returned non-zero (might not support --version)
                # Fallback to shutil.which to see if it's at least in the PATH
                if shutil.which(prog):
                    items.append(SystemCheckItem(name=prog, exists=True, message="Executable found, but failed retrieve its version"))
                else:
                    items.append(SystemCheckItem(name=prog, exists=False, message="Command not found or failed to execute"))
                    overall_success = False
        except (subprocess.SubprocessError, FileNotFoundError, Exception) as e:
            items.append(SystemCheckItem(name=prog, exists=False, message=str(e)))
            overall_success = False

    return SystemCheckResponse(success=overall_success, items=items)


@router.post("", response_model=InstallationResponse)
async def install_application(payload: InstallationRequest, background_tasks: BackgroundTasks):
    """Perform first-time installation for the application (database + admin user)."""

    if is_application_installed():
        raise HTTPException(status_code=409, detail="Application is already installed")

    await initialize_application_installation(
        database_url=payload.database_url,
        admin_username=payload.admin_username,
        admin_email=payload.admin_email,
        admin_password=payload.admin_password,
    )

    background_tasks.add_task(_restart_process)

    return InstallationResponse(installed=True, message="Application installed successfully")
