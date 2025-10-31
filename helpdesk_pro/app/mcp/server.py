"""
FastAPI application exposing MCP-compatible endpoints.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import get_settings
from .tools.base import ToolExecutionError
from .tools.registry import invoke_tool, list_tool_metadata

logger = logging.getLogger("helpdesk_pro.mcp")


class InvokeRequest(BaseModel):
    tool: str = Field(..., description="Tool name")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class InvokeResponse(BaseModel):
    tool: str
    elapsed_ms: int
    data: Dict[str, Any]


class ToolListResponse(BaseModel):
    tools: List[Dict[str, Any]]


def create_app() -> FastAPI:
    app = FastAPI(title="Helpdesk Pro MCP Server", version="0.1.0")

    current_settings = get_settings()
    if current_settings.allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=current_settings.allowed_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/healthz", tags=["system"])
    async def healthcheck() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/mcp/tools", response_model=ToolListResponse, tags=["mcp"])
    async def get_tools() -> ToolListResponse:
        metadata = list_tool_metadata()
        return ToolListResponse(tools=[meta.model_dump() for meta in metadata])

    @app.post("/mcp/invoke", response_model=InvokeResponse, tags=["mcp"])
    async def invoke(request: InvokeRequest) -> InvokeResponse:
        started = time.perf_counter()
        try:
            result = await invoke_tool(request.tool, request.arguments)
        except ToolExecutionError as exc:
            logger.warning("ToolExecutionError: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": str(exc), "tool": request.tool},
            ) from exc
        except Exception as exc:  # pragma: no cover - safety net
            logger.exception("Unexpected MCP error")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "Unexpected server error", "tool": request.tool},
            ) from exc
        elapsed = int((time.perf_counter() - started) * 1000)
        logger.info("tool=%s elapsed_ms=%s", request.tool, elapsed)
        return InvokeResponse(tool=request.tool, elapsed_ms=elapsed, data=result)

    return app


app = create_app()
