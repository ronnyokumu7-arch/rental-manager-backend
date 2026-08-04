"""
Top-level Payments Orchestrator.
Re-exports the aggregated payment router for main.py registration.
"""
from app.routers.payment import router

__all__ = ["router"]
