"""
Server launcher for AgenticInvoiceIntelligence.

Starts the FastAPI application with Uvicorn. Initializes the database
and seeds reference data on startup.
"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router
from src.data.database import bootstrap


def create_app() -> FastAPI:
    app = FastAPI(
        title="AgenticInvoiceIntelligence",
        description=(
            "Multi-agent AI system for intelligent invoice processing with "
            "governance-first design. Processes invoices through a 5-agent "
            "pipeline with inline governance gates, anomaly detection, and "
            "immutable audit trail."
        ),
        version="1.0.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    @app.on_event("startup")
    def on_startup():
        bootstrap()

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "run_server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
