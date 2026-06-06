"""Installation state and bootstrap helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from server.core.config import settings
from server.core.security import hash_password
from server.db import Base, make_async_engine
from server.models.models import User


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"


def is_application_installed() -> bool:
    return bool(settings.installation_completed)

def _format_env_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"' if any(ch.isspace() for ch in value) or value == "" else value


def update_env_file(values: dict[str, str | None]) -> None:
    existing_lines: list[str] = []
    existing_map: dict[str, str] = {}

    if ENV_PATH.exists():
        existing_lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
        for line in existing_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, current_value = stripped.split("=", 1)
            existing_map[key.strip()] = current_value.strip()

    for key, value in values.items():
        if value is None:
            existing_map.pop(key, None)
        else:
            existing_map[key] = _format_env_value(value)

    rendered_lines = []
    seen_keys: set[str] = set()
    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            rendered_lines.append(line)
            continue

        key = stripped.split("=", 1)[0].strip()
        if key in existing_map:
            rendered_lines.append(f"{key}={existing_map[key]}")
            seen_keys.add(key)
        else:
            rendered_lines.append(line)

    for key, value in existing_map.items():
        if key not in seen_keys:
            rendered_lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(rendered_lines).rstrip() + "\n", encoding="utf-8")


async def initialize_application_installation(
    *,
    database_url: str,
    admin_username: str,
    admin_email: str | None,
    admin_password: str,
) -> dict[str, Any]:
    """Initialize the application database and create the admin user."""

    engine = make_async_engine(database_url)
    session_factory = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            result = await session.execute(select(User).where(User.username == admin_username))
            user = result.scalars().first()
            
            if user:
                user.email = admin_email
                user.hashed_password = hash_password(admin_password)
            else:
                session.add(
                    User(
                        username=admin_username,
                        email=admin_email,
                        hashed_password=hash_password(admin_password),
                    )
                )

            await session.commit()
    finally:
        await engine.dispose()

    update_env_file(
        {
            "DATABASE_URL": database_url,
            "INSTALLATION_COMPLETED": "true",
        }
    )

    state = {
        "installed": True
    }
    
    return state


async def verify_database_connection(database_url: str) -> tuple[bool, str]:
    """Verify the database connection."""
    engine = make_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            await conn.execute(select(1))
        return True, "Database connection successful"
    except Exception as e:
        return False, str(e)
    finally:
        await engine.dispose()



def get_installation_status() -> dict[str, Any]:
    if settings.installation_completed:
        return {
            "installed": True,
        }

    return {
        "installed": False,
    }
