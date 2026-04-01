from fastapi import FastAPI
from src.api.routes import router

app = FastAPI(
    title="...",
    description="...",
    version="1.0.0"
)

app.include_router(router)
