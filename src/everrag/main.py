"""FastAPI 应用入口。"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from everrag.api.routes import router
from everrag.container import AppContainer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def create_app(container: AppContainer | None = None) -> FastAPI:
    app = FastAPI(
        title="EverRAG Agent",
        version="0.1.0",
        description="殡葬服务智能咨询助手 · 阶段 1 MVP",
    )
    app.state.container = container or AppContainer()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
