import json
import os
from datetime import timedelta
from dotenv import load_dotenv
load_dotenv()


def _float_env(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _list_env(key: str, default: list[str]) -> list[str]:
    raw = os.getenv(key)
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (json.JSONDecodeError, TypeError):
        pass
    return [item.strip() for item in raw.split(",") if item.strip()]


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'changeme')
    SQLALCHEMY_DATABASE_URI = os.getenv('SQLALCHEMY_DATABASE_URI')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = os.getenv('SQLALCHEMY_ECHO', 'False').lower() == 'true'
    MAIL_SERVER = os.getenv('MAIL_SERVER')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    LANGUAGES = ['en', 'el']
    BABEL_DEFAULT_LOCALE = os.getenv('DEFAULT_LANGUAGE', 'en')
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=45)
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
    JWT_SECRET_KEY = os.getenv('SECRET_KEY', 'changeme')
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    BASE_URL = os.getenv('BASE_URL')
    SECURITY_HEADERS = {
        "Content-Security-Policy": "default-src 'self'; img-src 'self' data:;",
        "X-Frame-Options": "DENY",
        "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload"
    }
    KNOWLEDGE_UPLOAD_FOLDER = os.path.join(os.getcwd(), 'instance', 'knowledge_uploads')
    COLLAB_UPLOAD_FOLDER = os.path.join(os.getcwd(), 'instance', 'chat_uploads')
    ASSISTANT_UPLOAD_FOLDER = os.path.join(os.getcwd(), 'instance', 'assistant_uploads')

    LANGUAGES = ['en', 'el']
    BABEL_DEFAULT_LOCALE = 'en'
    BABEL_TRANSLATION_DIRECTORIES = os.path.join(
        os.path.dirname(__file__), 'translations')
    UI_FONT_SCALE = _float_env('UI_FONT_SCALE', 0.95)
    UI_NAVBAR_HEIGHT = _float_env('UI_NAVBAR_HEIGHT', 30.0)
    UI_FOOTER_HEIGHT = _float_env('UI_FOOTER_HEIGHT', 35.0)
    UI_DATATABLE_HEADER_FONT_SIZE = _float_env('UI_DATATABLE_HEADER_FONT_SIZE', 0.95)
    ASSISTANT_ENABLE_LLM_OVERRIDE = os.getenv('ASSISTANT_ENABLE_LLM_OVERRIDE', 'True').lower() == 'true'
    try:
        ASSISTANT_TOOL_CALL_DEPTH_LIMIT = int(os.getenv('ASSISTANT_TOOL_CALL_DEPTH_LIMIT', '-1'))
    except (TypeError, ValueError):
        ASSISTANT_TOOL_CALL_DEPTH_LIMIT = -1
    MCP_ENABLED = os.getenv('MCP_ENABLED', 'True').lower() not in {'0', 'false', 'no'}
    MCP_HOST = os.getenv('MCP_HOST', '127.0.0.1')
    MCP_PORT = int(os.getenv('MCP_PORT', 8081))
    MCP_BASE_URL = os.getenv('MCP_BASE_URL')
    MCP_DATABASE_URL = os.getenv('MCP_DATABASE_URL')
    MCP_LOG_LEVEL = os.getenv('MCP_LOG_LEVEL', LOG_LEVEL)
    MCP_ALLOWED_ORIGINS = _list_env('MCP_ALLOWED_ORIGINS', [])
    MCP_MAX_ROWS = int(os.getenv('MCP_MAX_ROWS', 1000))
    MCP_REQUEST_TIMEOUT_SECONDS = int(os.getenv('MCP_REQUEST_TIMEOUT', 10))
    MCP_KEEP_ALIVE_SECONDS = int(os.getenv('MCP_KEEP_ALIVE', 5))
    MCP_ACCESS_LOG = os.getenv('MCP_ACCESS_LOG', 'False').lower() in {'1', 'true', 'yes'}
