"""Serve the built UI without exposing files outside its public directory."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, directory: Path) -> None:
    root = directory.resolve()
    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        try:
            candidate = (root / full_path).resolve()
        except (OSError, RuntimeError, ValueError):
            raise HTTPException(status_code=404, detail="Not found")
        if not candidate.is_relative_to(root):
            raise HTTPException(status_code=404, detail="Not found")
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        # Deep links need the entry point; unknown API routes should stay 404s.
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(root / "index.html")
