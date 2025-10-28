import os
from datetime import timedelta
from dotenv import load_dotenv
load_dotenv()


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
    APP_VERSION = os.getenv('APP_VERSION', '1.1.10')
