"""
Clients router - aggregates all client-related endpoints.
"""
from fastapi import APIRouter
from app.routers.client import router as client_router

# Re-export the router for use in main.py
router = client_router
