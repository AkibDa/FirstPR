import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi.responses import JSONResponse
from fastapi import Request

from limiter import limiter
from config import configure_logging, settings
from api import router

configure_logging()

import logging
logger = logging.getLogger(__name__)

settings.validate()

logger.info(
    "Starting FirstPR  env=%s  llm=%s  embed=%s",
    settings.app_env,
    settings.llm_model,
    settings.embed_model,
)

app = FastAPI(
    title="FirstPR",
    description=(
        "AI-powered multi-agent mentorship system for beginner open-source "
        "contributors. Ingests any GitHub repository on-demand and guides "
        "contributors through issues using a hybrid RAG pipeline backed by "
        "persistent ChromaDB vector storage."
    ),
    version="2.0.0",
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://firstpr-mentor.vercel.app", 
        "http://localhost:5173",             
        "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request, exc):
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "detail": "Too many requests. Please slow down."
        },
    )


@app.get("/")
@limiter.limit("5/minute")
def root(request: Request,):
    return {
        "message": "Welcome to FirstPR API",
        "env":     settings.app_env,
        "llm":     settings.llm_model,
    }


@app.get("/config")
@limiter.limit("5/minute")
def show_config(request: Request,):
    """Expose non-sensitive runtime config for debugging."""
    return {
        "app_env":          settings.app_env,
        "llm_model":        settings.llm_model,
        "embed_model":      settings.embed_model,
        "llm_base_url":     settings.llm_base_url,
        "cloud_embed_url":  settings.cloud_embed_url  if settings.is_production else "n/a (dev)",
        "cloud_rerank_url": settings.cloud_rerank_url if settings.is_production else "n/a (dev)",
        "chroma_path":      settings.chroma_path,
        "embed_batch_size": settings.embed_batch_size,
        "llm_timeout":      settings.llm_timeout,
    }

app.include_router(router)
