from fastapi import APIRouter

from app.api.routes.courses import router as courses_router
from app.api.routes.generation import router as generation_router
from app.api.routes.health import router as health_router
from app.api.routes.knowledge import router as knowledge_router
from app.api.routes.materials import router as materials_router
from app.api.routes.projects import router as projects_router
from app.api.routes.rag import router as rag_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health_router)
api_router.include_router(projects_router)
api_router.include_router(courses_router)
api_router.include_router(materials_router)
api_router.include_router(generation_router)
api_router.include_router(knowledge_router)
api_router.include_router(rag_router)
