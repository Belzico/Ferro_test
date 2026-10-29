from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.jobs import router as jobs_router
from app.config import settings
from app.database import init_db


def create_app(initialize_database: bool = True) -> FastAPI:

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if initialize_database:
            init_db()
        yield

    application = FastAPI(
        title=settings.app.name,
        debug=settings.app.debug,
        lifespan=lifespan,
    )

    application.include_router(jobs_router)

    return application


app = create_app()
