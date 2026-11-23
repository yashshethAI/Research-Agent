from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api.chat import router as chat_router
from backend.app.api.conversations import router as conversations_router
from backend.app.api.documents import router as documents_router
from backend.app.api.research import router as research_router
from backend.app.core.config import settings
from backend.app.llm.factory import llm_factory
from backend.app.schemas.api import ConfigStatusResponse

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("gst_practice_copilot")

app = FastAPI(
    title=settings.APP_NAME,
    description="Backend API for Indian GST Practice Copilot & Legal Research Engine",
    version="1.0.0",
)

# CORS Middleware (Localhost-first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permits local Streamlit connection
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API Routers under /api/v1
api_v1_prefix = "/api/v1"
app.include_router(chat_router, prefix=api_v1_prefix)
app.include_router(conversations_router, prefix=api_v1_prefix)
app.include_router(research_router, prefix=api_v1_prefix)
app.include_router(documents_router, prefix=api_v1_prefix)


@app.get("/api/v1/health")
async def health_check() -> dict:
    """Basic health check endpoint."""
    llm_ok, llm_msg = await llm_factory.health_check() if llm_factory.is_configured() else (False, "LLM Not Configured")
    return {
        "status": "healthy",
        "app_name": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "timestamp": datetime.now(UTC).isoformat(),
        "llm_status": {
            "configured": llm_factory.is_configured(),
            "reachable": llm_ok,
            "message": llm_msg,
        },
        "search_status": {
            "configured": settings.is_search_configured,
            "provider": settings.SEARCH_PROVIDER,
        },
    }


@app.get("/api/v1/config/status", response_model=ConfigStatusResponse)
async def config_status() -> ConfigStatusResponse:
    """Detailed configuration readiness status for frontend display."""
    data_writable = False
    try:
        test_file = settings.root_data_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
        data_writable = True
    except Exception:
        data_writable = False

    return ConfigStatusResponse(
        app_name=settings.APP_NAME,
        app_env=settings.APP_ENV,
        llm_configured=llm_factory.is_configured(),
        llm_base_url=settings.LLM_BASE_URL,
        llm_model=settings.LLM_MODEL,
        search_configured=settings.is_search_configured,
        search_provider=settings.SEARCH_PROVIDER,
        official_domains_count=len(settings.allowed_domains),
        data_dir_writable=data_writable,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception at {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred.", "error": str(exc)},
    )
