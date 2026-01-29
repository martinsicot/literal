"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from literal.api.routes import router as api_router
from literal.config import get_settings
from literal.models.base import close_db, init_db

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    await init_db()
    yield
    # Shutdown
    await close_db()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Literal",
        description="i+1 Sentence Builder for Language Learning",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.debug,
    )

    # Mount static files
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # Include API routes
    app.include_router(api_router, prefix="/api")

    # Templates
    templates = Jinja2Templates(directory=TEMPLATES_DIR) if TEMPLATES_DIR.exists() else None

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index(request: Request):
        """Render main page."""
        if templates:
            return templates.TemplateResponse("index.html", {"request": request})
        return HTMLResponse(content="<h1>Literal</h1><p>API: <a href='/docs'>/docs</a></p>")

    @app.get("/practice", response_class=HTMLResponse, include_in_schema=False)
    async def practice(request: Request):
        """Render practice page."""
        if templates:
            return templates.TemplateResponse("practice.html", {"request": request})
        return HTMLResponse(content="<h1>Practice</h1>")

    @app.get("/words", response_class=HTMLResponse, include_in_schema=False)
    async def words(request: Request):
        """Render words page."""
        if templates:
            return templates.TemplateResponse("words.html", {"request": request})
        return HTMLResponse(content="<h1>Words</h1>")

    @app.get("/stats", response_class=HTMLResponse, include_in_schema=False)
    async def stats(request: Request):
        """Render stats page."""
        if templates:
            return templates.TemplateResponse("stats.html", {"request": request})
        return HTMLResponse(content="<h1>Stats</h1>")

    @app.get("/import", response_class=HTMLResponse, include_in_schema=False)
    async def import_page(request: Request):
        """Render import page."""
        if templates:
            return templates.TemplateResponse("import.html", {"request": request})
        return HTMLResponse(content="<h1>Import</h1>")

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "healthy"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "literal.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
