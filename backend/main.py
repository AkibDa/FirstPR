import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api import router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="GitHub Issue Navigator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the routes defined in api.py
app.include_router(router)