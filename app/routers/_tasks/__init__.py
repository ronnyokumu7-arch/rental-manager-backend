from fastapi import APIRouter
from . import feed, lifecycle, management

router = APIRouter(prefix="/tasks", tags=["tasks"])

router.include_router(feed.router)
router.include_router(lifecycle.router)
router.include_router(management.router)
