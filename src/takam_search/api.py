"""FastAPI service.

    uvicorn takam_search.api:app --app-dir src
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from .answerer import LLM, Answerer, build_llm
from .config import PROJECT_ROOT, Settings, get_settings
from .ingest import build as build_index_from_raw
from .retriever import Retriever

log = logging.getLogger("takam_search.api")
WEB_DIR = PROJECT_ROOT / "web"
WEB_INDEX = WEB_DIR / "index.html"


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    include_expired: bool = False


def create_app(settings: Settings | None = None, llm: LLM | None = None, use_settings_llm: bool = True) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # First run convenience: build the index from the committed sample if missing.
        if not settings.db_path.exists() and settings.manifest_path.exists():
            log.info("index missing; building from %s", settings.raw_dir)
            build_index_from_raw(settings)
        yield

    app = FastAPI(title="Takam search", version="0.1.0", lifespan=lifespan)
    retriever = Retriever(settings.db_path)
    active_llm = llm if llm is not None else (build_llm(settings) if use_settings_llm else None)
    answerer = Answerer(retriever, active_llm, k=settings.search_top_k)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        log.info("%s %s -> %d (%.0f ms)", request.method, request.url.path, response.status_code,
                 (time.perf_counter() - start) * 1000)
        return response

    @app.get("/health")
    def health():
        """Readiness: index present, readable and non-empty."""
        try:
            stats = retriever.stats()
        except Exception as exc:  # missing/corrupt index file
            return JSONResponse(status_code=503, content={"status": "unavailable", "error": str(exc)})
        if stats["chunks"] == 0:
            return JSONResponse(status_code=503, content={"status": "empty_index", **stats})
        return {
            "status": "ok",
            **stats,
            "llm": {"enabled": active_llm is not None, "provider": settings.llm_provider if active_llm else None,
                    "model": settings.llm_model if active_llm else None},
        }

    @app.get("/search")
    def search(
        q: str = Query(min_length=1, max_length=1000),
        include_expired: bool = False,
        k: int = Query(default=settings.search_top_k, ge=1, le=50),
    ):
        hits = retriever.search(q, k, include_expired)
        return {
            "query": q,
            "hits": [h.to_dict() for h in hits],
            "related": retriever.related([h.doc_code for h in hits], include_expired),
        }

    @app.post("/ask")
    def ask(body: AskRequest):
        if not body.question.strip():
            raise HTTPException(status_code=422, detail="question is empty")
        return answerer.ask(body.question, body.include_expired).to_dict()

    @app.get("/", include_in_schema=False)
    def ui():
        return FileResponse(WEB_INDEX, media_type="text/html; charset=utf-8")

    @app.get("/widget.js", include_in_schema=False)
    def widget():
        """Embeddable launcher: <script src=".../widget.js" defer></script>."""
        return FileResponse(WEB_DIR / "widget.js", media_type="application/javascript; charset=utf-8")

    @app.get("/demo", include_in_schema=False)
    def demo():
        """A sample host page with the widget embedded."""
        return FileResponse(WEB_DIR / "demo.html", media_type="text/html; charset=utf-8")

    return app


def _make_default_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return create_app()


# Created lazily by uvicorn ("takam_search.api:app"); tests call create_app() directly.
def __getattr__(name: str):
    if name == "app":
        global app
        app = _make_default_app()
        return app
    raise AttributeError(name)
