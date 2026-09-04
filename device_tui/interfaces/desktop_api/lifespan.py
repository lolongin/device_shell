"""FastAPI lifecycle for backend-owned resources."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from .context import BackendContext


def build_lifespan(ctx: BackendContext):
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        ctx.desktop.task_service.bind_runner_loop(asyncio.get_running_loop())
        yield
        await ctx.desktop.task_service.close()
        await ctx.desktop.upgrades.close()
        await ctx.desktop.package_builds.close()
        await ctx.desktop.transfers.close()
        await ctx.desktop.automation.close()
        ctx.terminal_executor.close()
        await ctx.desktop.sessions.close_all()
        ctx.hub.shutdown_logging()

    return lifespan
