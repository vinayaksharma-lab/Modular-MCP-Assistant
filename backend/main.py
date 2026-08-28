"""
FastAPI Backend Application
Entrypoint for the MCP-integrated modular chat system.
Provides REST endpoints for chat interactions, tool discovery, and health checks.
"""

import os
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from backend.mcp_client import mcp_client
from backend.llm_service import llm_service

# Load environment configuration
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("main_api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup and shutdown routines."""
    logger.info("Starting Modular MCP Chat Backend...")
    # Verify MCP server connectivity on startup
    try:
        health = await mcp_client.check_health()
        logger.info(f"MCP Server Health on startup: {health}")
    except Exception as e:
        logger.warning(f"MCP Server initial check warning: {e}")
    yield
    logger.info("Shutting down Modular MCP Chat Backend...")


# Initialize FastAPI app
app = FastAPI(
    title="Modular MCP Chat Application API",
    description="Full-stack modular agentic chat API with Model Context Protocol (MCP) tool integration",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins for local development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Pydantic Data Models ---

class MessageItem(BaseModel):
    role: str = Field(..., description="Role of the sender ('user' or 'assistant')")
    content: str = Field(..., description="Message text content")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User query or message")
    history: Optional[List[MessageItem]] = Field(
        default_factory=list,
        description="Previous conversation history"
    )


class ToolCallRecord(BaseModel):
    success: bool
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result: str
    error: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str = Field(..., description="LLM generated or synthesized response")
    tool_calls: List[ToolCallRecord] = Field(
        default_factory=list,
        description="Records of any MCP tools executed during this turn"
    )
    provider: str = Field(..., description="LLM / Agent provider used for this response")


class HealthResponse(BaseModel):
    status: str
    mcp_status: str
    discovered_tools: List[str]


# --- API Routes ---

@app.get("/api/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Returns backend and MCP server health status."""
    mcp_health = await mcp_client.check_health()
    return HealthResponse(
        status="ok",
        mcp_status=mcp_health.get("status", "unknown"),
        discovered_tools=mcp_health.get("tools", [])
    )


@app.get("/api/tools", tags=["MCP Tools"])
async def get_available_tools():
    """Lists all tools currently exposed by the connected MCP server."""
    tools = await mcp_client.list_tools()
    return {
        "count": len(tools),
        "tools": tools
    }


@app.post("/api/chat", response_model=ChatResponse, tags=["Chat"])
async def chat_endpoint(request: ChatRequest):
    """
    Main chat endpoint.
    Accepts user prompt and history, executes required MCP tools, and returns the response.
    """
    clean_msg = request.message.strip()
    if not clean_msg:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Message cannot be empty."
        )

    try:
        # Convert history Pydantic models to dicts
        history_dicts = [{"role": m.role, "content": m.content} for m in request.history]

        # Call LLM service with MCP integration
        result = await llm_service.generate_response(
            user_message=clean_msg,
            chat_history=history_dicts
        )

        return ChatResponse(
            reply=result["reply"],
            tool_calls=result.get("tool_calls", []),
            provider=result.get("provider", "unknown")
        )
    except Exception as e:
        logger.error(f"Error processing chat request: {e}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": f"An error occurred while generating the response: {str(e)}",
                "reply": f"⚠️ Server Error: {str(e)}",
                "tool_calls": [],
                "provider": "error"
            }
        )


# --- Optional Static Files Serving (Frontend) ---
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/css", StaticFiles(directory=str(frontend_path / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(frontend_path / "js")), name="js")
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(frontend_path / "index.html")


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("backend.main:app", host=host, port=port, reload=True)
