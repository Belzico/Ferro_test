from fastapi import FastAPI
from app.config import settings


app = FastAPI(
    title=settings.app.name,
    debug=settings.app.debug
)
