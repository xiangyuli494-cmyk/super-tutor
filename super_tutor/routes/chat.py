"""Standalone AI chat route — direct CLI call without workflow."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from super_tutor.config import ForgeConfig
from super_tutor.core.cli_backend import CLIBackend
from super_tutor.models import StandardResponse

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    role: str = Field(..., description="Role: claude or codex")
    message: str = Field(..., min_length=1, description="User message")


@router.post("/chat", response_model=StandardResponse[dict])
async def chat(request: ChatRequest) -> StandardResponse[dict]:
    """Send a message to Claude or Codex CLI and return the response."""
    if request.role not in ("claude", "codex"):
        raise HTTPException(
            status_code=400,
            detail={
                "code": 1001,
                "message": f"Invalid role '{request.role}'. Use 'claude' or 'codex'.",
                "data": None,
            },
        )

    config = ForgeConfig.get_instance()
    backend = CLIBackend(config)

    try:
        response = await backend.chat_with_file_context(
            role="claude-a" if request.role == "claude" else "codex",
            user_message=request.message,
            files=[],
            tier="medium",
            system_prompt=None,
        )
        return StandardResponse(code=0, message="ok", data={"reply": response})
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "code": 2001,
                "message": f"Chat failed: {exc}",
                "data": None,
            },
        )
