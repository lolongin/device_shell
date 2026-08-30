"""MCP HTTP bridge route."""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from ..dependencies import authorize, get_context

router = APIRouter(prefix="/api/v1", tags=["mcp"], dependencies=[Depends(authorize)])

@router.post("/mcp/{tool}")
async def invoke_mcp_tool(tool: str, request: dict[str, object], ctx=Depends(get_context)) -> JSONResponse:
    status, payload = await ctx.mcp_service.invoke(tool, dict(request))
    return JSONResponse(status_code=status, content=payload)
