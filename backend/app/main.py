from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.translations import public_router, router
from app.core.auth import auth_router
from app.core.config import CORS_ORIGINS

app = FastAPI(
    title="Libris API",
    description="Translate books with Gemini Cloud API or offline Argos Translate.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(public_router)
app.include_router(router)


@app.get("/")
async def root():
    return {
        "name": "Libris API",
        "docs": "/docs",
        "health": "/api/health",
    }
