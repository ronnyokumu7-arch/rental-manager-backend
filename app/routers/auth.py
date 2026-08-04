"""
Top-level Auth Orchestrator.
Re-exports the aggregated auth router for main.py registration.
"""
from app.routers._auth import router

__all__ = ["router"]
