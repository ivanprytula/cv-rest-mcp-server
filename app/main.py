import base64
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.cv_data import CV_DATA
from app.pdf_generator import generate_cv_pdf, list_themes
from app.rate_limiter import limiter
from app.routes import router
from app.settings import settings


mcp = FastMCP("cv-mcp-agent")


@mcp.tool
def get_cv() -> dict:
    return CV_DATA


@mcp.tool
def get_available_themes() -> list[str]:
    return list_themes()


@mcp.tool
def generate_cv_pdf_tool(theme: str) -> str:
    try:
        pdf_bytes = generate_cv_pdf(theme, CV_DATA)
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(str(exc)) from exc
    return base64.b64encode(pdf_bytes).decode("utf-8")


mcp_app = mcp.http_app(path="/")


@asynccontextmanager
async def lifespan(app):
    async with mcp_app.lifespan(app):
        yield


app = FastAPI(title="CV MCP Agent", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(
    RateLimitExceeded,
    lambda request, exc: _rate_limit_exceeded_handler(request, exc),
)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/mcp", mcp_app)
app.include_router(router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
