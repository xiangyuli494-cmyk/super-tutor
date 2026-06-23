"""FastAPI application entry point for the Forge Engine.

Provides the local HTTP server that the Electron shell communicates with.
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from super_tutor import __version__
from super_tutor.config import ForgeConfig
from super_tutor.models import StandardResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler.

    On startup: initialise the database connection.
    On shutdown: clean up resources.
    """
    # TODO(M1): initialise database connection pool
    config = ForgeConfig.get_instance()
    print(f"[forge-engine] Starting up. Projects root: {config.projects_root}")
    yield
    # TODO(M1): close database connection pool
    print("[forge-engine] Shutting down.")


app = FastAPI(
    title="Forge Engine",
    version=__version__,
    lifespan=lifespan,
)

# CORS: allow localhost origins only.
# The server binds 127.0.0.1, so wildcard CORS is safe, but we explicitly
# list the expected origins for defence-in-depth.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:*",
        "http://127.0.0.1:*",
    ],
    # Starlette does not support glob patterns natively; the "*" entries
    # above are documentation-only.  In practice Electron renderer origins
    # vary by port, so we fall back to allow_origin_regex for real matching.
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health", response_model=StandardResponse[dict])
async def health_check() -> StandardResponse[dict]:
    """Health check endpoint.

    Returns the engine version and confirms the service is running.

    Returns:
        StandardResponse with version info in the data field.
    """
    return StandardResponse(
        code=0,
        message="ok",
        data={"version": __version__},
    )


from super_tutor.routes import project, workflow, artifact, settings, files, chat

app.include_router(project.router, prefix="/api/v1")
app.include_router(workflow.router, prefix="/api/v1")
app.include_router(artifact.router, prefix="/api/v1")
app.include_router(settings.router, prefix="/api/v1")
app.include_router(files.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")


def main() -> None:
    """Entry point for running the server directly.

    Uses uvicorn to serve the FastAPI app.  Port selection priority:

    1. ``FORGE_PORT`` environment variable
    2. ``--port`` CLI argument (passed by Electron's PythonProcessManager)
    3. Default fallback port 8765 (browser direct-connect mode)
    """
    import argparse
    import os
    import uvicorn

    # Parse --port from CLI (used by Electron's PythonProcessManager).
    parser = argparse.ArgumentParser(description="Forge Engine server")
    parser.add_argument("--port", type=int, default=None, help="Port to listen on")
    args = parser.parse_args()

    # Priority: CLI arg > env var > default 8765
    port = args.port or int(os.environ.get("FORGE_PORT", "8765"))

    uvicorn.run(
        "super_tutor.main:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
