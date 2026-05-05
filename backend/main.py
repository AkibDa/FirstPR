import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="FirstPR")

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