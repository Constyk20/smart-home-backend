from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.mongodb import close_mongo_connection, connect_to_mongo
from app.routers import (
    activity,
    auth,
    automation,
    automation_history,
    devices,
    energy,
    houses,
    ml,
    recommendations,
    rooms,
    schedules,
    simulation,
    ws,
)
from app.services.simulation_worker import start_simulation_worker, stop_simulation_worker


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    start_simulation_worker()
    yield
    await stop_simulation_worker()
    await close_mongo_connection()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(houses.router, prefix=settings.API_V1_PREFIX)
app.include_router(rooms.router, prefix=settings.API_V1_PREFIX)
app.include_router(devices.router, prefix=settings.API_V1_PREFIX)
app.include_router(activity.router, prefix=settings.API_V1_PREFIX)
app.include_router(simulation.router, prefix=settings.API_V1_PREFIX)
app.include_router(energy.router, prefix=settings.API_V1_PREFIX)
app.include_router(automation.router, prefix=settings.API_V1_PREFIX)
app.include_router(automation_history.router, prefix=settings.API_V1_PREFIX)
app.include_router(ml.router, prefix=settings.API_V1_PREFIX)
app.include_router(recommendations.router, prefix=settings.API_V1_PREFIX)
app.include_router(schedules.router, prefix=settings.API_V1_PREFIX)
app.include_router(ws.router)


@app.get("/")
async def root():
    return {
        "message": "AI Virtual Smart Home API is running",
        "environment": settings.APP_ENV,
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
