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


def _bool_env(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes"}


def _int_env(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _bytes_env(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw == "":
        return default
    raw = raw.strip().lower()
    multipliers = {
        "kb": 1024,
        "k": 1024,
        "mb": 1024 * 1024,
        "m": 1024 * 1024,
        "gb": 1024 * 1024 * 1024,
        "g": 1024 * 1024 * 1024,
    }
    try:
        for suffix, multiplier in multipliers.items():
            if raw.endswith(suffix):
                return int(float(raw[:-len(suffix)].strip()) * multiplier)
        return int(raw)
    except (TypeError, ValueError):
        return default


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = os.getenv('SQLALCHEMY_DATABASE_URI')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = os.getenv('SQLALCHEMY_ECHO', 'False').lower() == 'true'
    MAIL_SERVER = os.getenv('MAIL_SERVER')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    MAIL_FALLBACK_TO_NO_AUTH = os.getenv(
        'MAIL_FALLBACK_TO_NO_AUTH', 'True').lower() == 'true'
    LANGUAGES = ['en', 'el']
    BABEL_DEFAULT_LOCALE = os.getenv('DEFAULT_LANGUAGE', 'en')
    SESSION_TIMEOUT_MINUTES = _int_env('SESSION_TIMEOUT_MINUTES', 45)
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
    SESSION_REFRESH_EACH_REQUEST = _bool_env('SESSION_REFRESH_EACH_REQUEST', True)
    REMEMBER_COOKIE_DURATION = timedelta(days=_int_env('REMEMBER_COOKIE_DAYS', 30))
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
    LOG_FILE_LEVEL = os.getenv('LOG_FILE_LEVEL')
    if LOG_FILE_LEVEL:
        LOG_FILE_LEVEL = LOG_FILE_LEVEL.upper()
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY') or SECRET_KEY
    AUTH_METHODS = [
        method.strip().lower()
        for method in _list_env("AUTH_METHODS", ["local"])
    ]
    AUTH_LDAP_ENABLED = _bool_env("AUTH_LDAP_ENABLED", False)
    AUTH_LDAP_SERVER_URI = os.getenv("AUTH_LDAP_SERVER_URI")
    AUTH_LDAP_PORT = int(os.getenv("AUTH_LDAP_PORT", 389))
    AUTH_LDAP_USE_SSL = _bool_env("AUTH_LDAP_USE_SSL", False)
    AUTH_LDAP_BIND_DN = os.getenv("AUTH_LDAP_BIND_DN")
    AUTH_LDAP_BIND_PASSWORD = os.getenv("AUTH_LDAP_BIND_PASSWORD")
    AUTH_LDAP_SEARCH_BASE = os.getenv("AUTH_LDAP_SEARCH_BASE")
    AUTH_LDAP_USER_ATTRIBUTE = os.getenv("AUTH_LDAP_USER_ATTRIBUTE", "sAMAccountName")
    AUTH_LDAP_USER_DN_TEMPLATE = os.getenv("AUTH_LDAP_USER_DN_TEMPLATE")
    AUTH_LDAP_DEFAULT_EMAIL_DOMAIN = os.getenv("AUTH_LDAP_DEFAULT_EMAIL_DOMAIN", "example.local")
    AUTH_SSO_ENABLED = _bool_env("AUTH_SSO_ENABLED", False)
    AUTH_SSO_CLIENT_ID = os.getenv("AUTH_SSO_CLIENT_ID")
    AUTH_SSO_CLIENT_SECRET = os.getenv("AUTH_SSO_CLIENT_SECRET")
    AUTH_SSO_METADATA_URL = os.getenv("AUTH_SSO_METADATA_URL")
    AUTH_SSO_SCOPE = os.getenv("AUTH_SSO_SCOPE", "openid email profile")
    AUTH_SSO_EMAIL_CLAIM = os.getenv("AUTH_SSO_EMAIL_CLAIM", "email")
    AUTH_SSO_USERNAME_CLAIM = os.getenv("AUTH_SSO_USERNAME_CLAIM", "preferred_username")
    AUTH_SSO_NAME_CLAIM = os.getenv("AUTH_SSO_NAME_CLAIM", "name")
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
    MAX_SIZE = _bytes_env('MAX_SIZE', 16 * 1024 * 1024)
    MAX_CONTENT_LENGTH = _bytes_env('MAX_CONTENT_LENGTH', MAX_SIZE)
    CONTRACT_DOCUMENT_MAX_SIZE = _bytes_env('CONTRACT_DOCUMENT_MAX_SIZE', MAX_SIZE)
    BASE_URL = os.getenv('BASE_URL')
    SECURITY_HEADERS = {
        "Content-Security-Policy": "default-src 'self'; img-src 'self' data:;",
        "X-Frame-Options": "DENY",
        "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload"
    }
    KNOWLEDGE_UPLOAD_FOLDER = os.path.join(
        os.getcwd(), 'instance', 'knowledge_uploads')
    COLLAB_UPLOAD_FOLDER = os.path.join(
        os.getcwd(), 'instance', 'chat_uploads')
    ASSISTANT_UPLOAD_FOLDER = os.path.join(
        os.getcwd(), 'instance', 'assistant_uploads')

    LANGUAGES = ['en', 'el']
    BABEL_DEFAULT_LOCALE = 'en'
    BABEL_TRANSLATION_DIRECTORIES = os.path.join(
        os.path.dirname(__file__), 'translations')
    UI_FONT_SCALE = _float_env('UI_FONT_SCALE', 0.95)
    UI_NAVBAR_HEIGHT = _float_env('UI_NAVBAR_HEIGHT', 30.0)
    UI_FOOTER_HEIGHT = _float_env('UI_FOOTER_HEIGHT', 35.0)
    UI_DATATABLE_HEADER_FONT_SIZE = _float_env(
        'UI_DATATABLE_HEADER_FONT_SIZE', 0.95)
    ASSISTANT_ENABLE_LLM_OVERRIDE = os.getenv(
        'ASSISTANT_ENABLE_LLM_OVERRIDE', 'True').lower() == 'true'
    try:
        ASSISTANT_TOOL_CALL_DEPTH_LIMIT = int(
            os.getenv('ASSISTANT_TOOL_CALL_DEPTH_LIMIT', '-1'))
    except (TypeError, ValueError):
        ASSISTANT_TOOL_CALL_DEPTH_LIMIT = -1
    COLLAB_ASSISTANT_ENABLED = os.getenv('COLLAB_ASSISTANT_ENABLED', 'True').lower() not in {
        '0', 'false', 'no'}
    MCP_ENABLED = os.getenv('MCP_ENABLED', 'True').lower() not in {
        '0', 'false', 'no'}
    MCP_HOST = os.getenv('MCP_HOST', '127.0.0.1')
    MCP_PORT = int(os.getenv('MCP_PORT', 8081))
    MCP_BASE_URL = os.getenv('MCP_BASE_URL')
    MCP_DATABASE_URL = os.getenv('MCP_DATABASE_URL')
    MCP_LOG_LEVEL = os.getenv('MCP_LOG_LEVEL', LOG_LEVEL)
    MCP_ALLOWED_ORIGINS = _list_env('MCP_ALLOWED_ORIGINS', [])
    MCP_MAX_ROWS = int(os.getenv('MCP_MAX_ROWS', 1000))
    MCP_REQUEST_TIMEOUT_SECONDS = int(os.getenv('MCP_REQUEST_TIMEOUT', 10))
    MCP_KEEP_ALIVE_SECONDS = int(os.getenv('MCP_KEEP_ALIVE', 5))
    MCP_ACCESS_LOG = os.getenv('MCP_ACCESS_LOG', 'False').lower() in {
        '1', 'true', 'yes'}
    APP_VERSION = os.getenv('APP_VERSION', '5.0.2')
    FLEET_INGEST_ENABLED = os.getenv('FLEET_INGEST_ENABLED', 'True').lower() not in {'0', 'false', 'no'}
    FLEET_INGEST_HOST = os.getenv('FLEET_INGEST_HOST', '0.0.0.0')
    FLEET_INGEST_PORT = int(os.getenv('FLEET_INGEST_PORT', 8449))
    FLEET_UPLOAD_FOLDER = os.path.join(os.getcwd(), 'instance', 'fleet_uploads')
    FLEET_AGENT_INSTALLER_PATH = os.getenv(
        'FLEET_AGENT_INSTALLER_PATH',
        os.path.join(os.getcwd(), 'instance', 'Telemetry_Agent.msi'),
    )
    FLEET_AGENT_INSTALLER_MAX_BYTES = int(os.getenv('FLEET_AGENT_INSTALLER_MAX_BYTES', 100 * 1024 * 1024))
    FLEET_AGENT_LINK_DEFAULT_TTL_DAYS = int(os.getenv('FLEET_AGENT_LINK_DEFAULT_TTL_DAYS', 7))
