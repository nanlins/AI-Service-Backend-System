from fastapi import APIRouter

from app.api.v1 import auth, health, messages, sessions, tasks, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(sessions.router)
api_router.include_router(messages.router)
api_router.include_router(tasks.router)
