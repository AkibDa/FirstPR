import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import router

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="FirstPR",
    description=(
        "AI-powered multi-agent mentorship system for beginner open-source contributors. "
        "Ingests any GitHub repository on-demand and guides contributors through issues "
        "using a hybrid RAG pipeline backed by persistent ChromaDB vector storage."
    ),
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"message": "Welcome to FirstPR API"}

app.include_router(router)
