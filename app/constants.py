from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
TEMPLATE_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"
THEMES_DIR = Path(__file__).resolve().parent / "themes"
EXAMPLE_CV_PATH = PROJECT_ROOT / "data" / "cv.example.json"
BINGO_CONTENT_PATH = CONFIG_DIR / "bingo_content.json"

PDF_CACHE_MAX_ENTRIES = 50
PDF_EXECUTOR_MAX_WORKERS = 2

MCP_READ_RATE_LIMIT = "30/minute"
MCP_PDF_RATE_LIMIT = "5/15minute"
