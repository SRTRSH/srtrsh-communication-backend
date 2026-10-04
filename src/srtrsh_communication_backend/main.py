from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI

from .db import close_pool, init_pool
from .orders.router import router as orders_router
from .catalog.router import router as catalog_router
from .channels.router import router as channels_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_pool()
    yield
    await close_pool()


app = FastAPI(
    title="SRTRSH Communication Backend",
    description="Canonical channel-agnostic conversational backend service for SRTRSH",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(orders_router)
app.include_router(catalog_router)
app.include_router(channels_router)


@app.get("/health", tags=["Health"])
async def health_check() -> dict:
    return {"status": "ok", "service": "srtrsh-communication-backend"}
