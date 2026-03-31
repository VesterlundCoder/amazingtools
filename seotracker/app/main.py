"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings
from app.scheduler import start_scheduler, stop_scheduler
from app.middleware.quota import QuotaMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("SEO Crawler API starting up")
    start_scheduler()
    yield
    logger.info("SEO Crawler API shutting down")
    stop_scheduler()


app = FastAPI(
    title="SEO Crawler API",
    description="Multi-tenant SEO crawler and technical audit engine",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(QuotaMiddleware)
app.include_router(router)


@app.get("/health")
async def health():
    from app.crawler.tasks import get_active_run_ids
    return {
        "status": "ok",
        "active_crawls": len(get_active_run_ids()),
    }
