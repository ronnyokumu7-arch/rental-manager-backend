"""
Top-level Invoice Orchestrator.
Re-exports the aggregated invoice router for main.py registration.
"""
from app.routers.invoice import router

__all__ = ["router"]
