"""AirWindow FastAPI Application Entry Point.

Pollution-aware outdoor activity scheduling core engine.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_plan import router as plan_router
from app.api.routes_trust import router as trust_router
from app.api.routes_whatif import router as whatif_router
from app.config import settings

app = FastAPI(
    title="AirWindow Core API",
    description=(
        "AirWindow helps users schedule outdoor activities during times of lower air pollution. "
        "Provides pure Python PM2.5 inhaled dose estimation, 15-minute slot optimization, "
        "baseline comparison, what-if scenarios, and forecast trust reporting."
    ),
    version=settings.version,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Enable CORS for local web development and frontend teammates
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get(
    "/health",
    tags=["System"],
    summary="Service health check",
    description="Returns the operational status, application version, and active provider.",
)
async def health_check() -> dict[str, str]:
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "service": "airwindow-core",
        "version": settings.version,
        "environment": settings.environment,
        "provider": settings.forecast_provider,
    }


# Include API routers
app.include_router(plan_router)
app.include_router(whatif_router)
app.include_router(trust_router)
