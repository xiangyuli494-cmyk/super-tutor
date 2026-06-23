"""Configuration management API routes.

Exposes endpoints to read and update Forge Engine settings stored in
``~/.forge/settings.json``.
"""

import json
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from super_tutor.config import ForgeConfig
from super_tutor.models import StandardResponse

router = APIRouter(prefix="/settings", tags=["settings"])

# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class UpdateSettingsRequest(BaseModel):
    """Request body for updating configuration values.

    Every field is optional — only the keys present in the request body are
    updated; omitted keys keep their current values.

    String fields use ``None`` as the "do not update" sentinel.  An explicit
    empty string (``""``) is treated as a request to clear that setting.
    ``token_budget_default`` uses ``-1`` as its sentinel since 0 is a valid
    budget value.
    """

    deepseek_api_key: Optional[str] = Field(
        default=None, description="DeepSeek API key"
    )
    deepseek_base_url: Optional[str] = Field(
        default=None, description="DeepSeek API base URL"
    )
    github_token: Optional[str] = Field(
        default=None, description="GitHub personal access token"
    )
    projects_root: Optional[str] = Field(
        default=None, description="Root directory for Forge projects"
    )
    token_budget_default: int = Field(
        default=-1, description="Default token budget per project"
    )
    model_heavy: Optional[str] = Field(
        default=None, description="Model for heavy tasks"
    )
    model_medium: Optional[str] = Field(
        default=None, description="Model for medium tasks"
    )
    model_light: Optional[str] = Field(
        default=None, description="Model for light tasks"
    )
    cli_mode: Optional[bool] = Field(
        default=None, description="Use local Claude/Codex CLI instead of API"
    )


# ---------------------------------------------------------------------------
# Known configuration keys (whitelist for writing)
# ---------------------------------------------------------------------------

_CONFIG_KEYS = {
    "deepseek_api_key",
    "deepseek_base_url",
    "github_token",
    "projects_root",
    "token_budget_default",
    "model_heavy",
    "model_medium",
    "model_light",
    "cli_mode",
}

# Keys whose values should be masked in the GET response.
_SECRET_KEYS = {"deepseek_api_key", "github_token"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings_file_path() -> Path:
    """Return the path to ``~/.forge/settings.json``."""
    return Path.home() / ".forge" / "settings.json"


def _mask_secret(value: str) -> str:
    """Return a masked version of *value* for display in the API.

    Preserves the first 4 and last 4 characters, replacing the middle with
    asterisks.  Short strings (<= 8 chars) are fully masked.
    """
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def _load_raw_settings() -> dict[str, Any]:
    """Load the raw settings dictionary from disk.

    Returns an empty dict when the file does not exist or cannot be parsed.
    """
    path = _settings_file_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_raw_settings(data: dict[str, Any]) -> None:
    """Write *data* to ``~/.forge/settings.json``, creating parent dirs."""
    path = _settings_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=StandardResponse[dict])
async def get_settings() -> StandardResponse[dict]:
    """Return the current engine configuration with secrets masked.

    Sensitive fields (API keys, tokens) are partially obscured so the
    response is safe to display in a UI.
    """
    config = ForgeConfig.get_instance()

    settings: dict[str, Any] = {
        "deepseek_api_key": _mask_secret(config.deepseek_api_key),
        "deepseek_base_url": config.deepseek_base_url,
        "github_token": _mask_secret(config.github_token),
        "projects_root": config.projects_root,
        "token_budget_default": config.token_budget_default,
        "model_heavy": config.model_heavy or "deepseek-chat",
        "model_medium": config.model_medium or "deepseek-chat",
        "model_light": config.model_light or "deepseek-chat",
        "cli_mode": config.cli_mode,
    }

    return StandardResponse(code=0, message="ok", data=settings)


@router.put("", response_model=StandardResponse[dict])
async def update_settings(body: UpdateSettingsRequest) -> StandardResponse[dict]:
    """Update one or more configuration values.

    Only the fields present in the request body are modified — unspecified
    settings retain their current values.  The ``ForgeConfig`` singleton is
    reset so that subsequent reads reflect the new values.

    ``None`` sentinel values are treated as "do not update."  An explicit
    empty string (``""``) clears the corresponding setting.  For
    ``token_budget_default``, ``-1`` is the sentinel.
    """
    # Load current settings from disk (source of truth).
    current = _load_raw_settings()

    # Merge only the explicitly-provided fields.
    updates: dict[str, Any] = {}
    if body.deepseek_api_key is not None:
        updates["deepseek_api_key"] = body.deepseek_api_key
    if body.deepseek_base_url is not None:
        updates["deepseek_base_url"] = body.deepseek_base_url
    if body.github_token is not None:
        updates["github_token"] = body.github_token
    if body.projects_root is not None:
        # Basic path validation: must be an absolute or expandable path.
        expanded = os.path.expanduser(body.projects_root)
        if not os.path.isabs(expanded):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": 1001,
                    "message": (
                        f"projects_root must be an absolute path. "
                        f"Got: '{body.projects_root}'."
                    ),
                    "data": None,
                },
            )
        updates["projects_root"] = body.projects_root
    if body.token_budget_default >= 0:
        updates["token_budget_default"] = body.token_budget_default
    if body.model_heavy is not None:
        updates["model_heavy"] = body.model_heavy
    if body.model_medium is not None:
        updates["model_medium"] = body.model_medium
    if body.model_light is not None:
        updates["model_light"] = body.model_light
    if body.cli_mode is not None:
        updates["cli_mode"] = body.cli_mode

    if not updates:
        raise HTTPException(
            status_code=400,
            detail={
                "code": 1001,
                "message": "No valid settings fields provided for update.",
                "data": None,
            },
        )

    # Filter to known keys only.
    sanitised = {k: v for k, v in updates.items() if k in _CONFIG_KEYS}
    current.update(sanitised)

    _save_raw_settings(current)

    # Reset the ForgeConfig singleton so the next call to get_instance()
    # re-reads from the updated file.
    ForgeConfig.reset()

    # Build a masked response.
    response_data: dict[str, Any] = {}
    for key, value in current.items():
        response_data[key] = _mask_secret(str(value)) if key in _SECRET_KEYS else value

    return StandardResponse(code=0, message="ok", data=response_data)
