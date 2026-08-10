"""Vercel Python Runtime entrypoint for the web API.

Workers, the scheduler, ERPNext, and object storage remain Compose services;
this function exposes the authenticated FastAPI web layer against Neon.
"""

from app.main import app

__all__ = ["app"]
