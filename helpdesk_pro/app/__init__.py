# -*- coding: utf-8 -*-
"""
Helpdesk Pro — Flask application factory
Full multilingual (English / Greek) support, Flask-Babel 3.x compatible.
"""

import os
import logging
from datetime import datetime
from flask import (
    Flask, render_template, request, session, g, current_app
)
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_mail import Mail
from flask_wtf import CSRFProtect
from flask_babel import Babel
from flask_jwt_extended import JWTManager
from logging.handlers import RotatingFileHandler
from config import Config

# ───────── Extensions ───────── #
db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
mail = Mail()
csrf = CSRFProtect()
jwt = JWTManager()
babel = Babel()


def create_app():
    app = Flask(__name__, template_folder="../templates",
                static_folder="../static")
    app.config.from_object(Config)
    app.config.setdefault("SECRET_KEY", os.urandom(24))
    app.config.setdefault("LANGUAGES", ["en", "el"])
    app.config.setdefault("BABEL_DEFAULT_LOCALE", "en")
    app.config.setdefault("BABEL_TRANSLATION_DIRECTORIES", "translations")

    # ───────── Init extensions ───────── #
    db.init_app(app)
    migrate.init_app(app, db)
    mail.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    jwt.init_app(app)

    # ───────── Flask-Login ───────── #
    from app.models.user import User

    @login_manager.user_loader
    def load_user(uid): return User.query.get(int(uid))

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    # ───────── Babel (immediate URL/session switch) ───────── #
    def get_locale():
        lang = request.args.get("lang")
        if lang in app.config["LANGUAGES"]:
            session["lang"] = lang
            g.locale = lang
            return lang
        stored = session.get("lang")
        if stored in app.config["LANGUAGES"]:
            g.locale = stored
            return stored
        best = request.accept_languages.best_match(app.config["LANGUAGES"])
        g.locale = best or app.config["BABEL_DEFAULT_LOCALE"]
        return g.locale

    babel.init_app(app, locale_selector=get_locale)

    @app.before_request
    def _set_g_locale():
        g.locale = get_locale()

    @app.context_processor
    def inject_globals():
        from app.navigation import get_navigation_for_user, is_feature_allowed
        from app.models import ChatMessage, ChatMembership, ChatMessageRead, AssistantConfig, AuthConfig

        chat_unread = 0
        if current_user.is_authenticated:
            chat_unread = (
                db.session.query(ChatMessage.id)
                .join(ChatMembership, (ChatMembership.conversation_id == ChatMessage.conversation_id) & (ChatMembership.user_id == current_user.id))
                .outerjoin(ChatMessageRead, (ChatMessageRead.message_id == ChatMessage.id) & (ChatMessageRead.user_id == current_user.id))
                .filter(ChatMessage.sender_id != current_user.id)
                .filter(ChatMessageRead.id.is_(None))
                .count()
            )

        assistant_widget = None
        auth_config = AuthConfig.load().to_dict()
        if current_user.is_authenticated and is_feature_allowed("assistant_widget", current_user):
            cfg = AssistantConfig.get()
            if cfg and cfg.is_enabled:
                assistant_widget = cfg.to_dict()

        return {
            "current_year": datetime.now().year,
            "current_lang": g.get("locale", app.config["BABEL_DEFAULT_LOCALE"]),
            "navigation": get_navigation_for_user(current_user),
            "chat_unread_count": chat_unread,
            "assistant_widget_config": assistant_widget,
            "auth_config": auth_config,
            "app_version": app.config.get("APP_VERSION", "1.0.0"),
        }

    # ───────── Blueprints ───────── #
    from app.auth.routes import auth_bp
    from app.tickets.routes import tickets_bp
    from app.users.routes import users_bp
    from app.dashboard.routes import dashboard_bp
    from app.api.routes import api_bp
    from app.inventory.routes import inventory_bp
    from app.networks.routes import networks_bp
    from app.collab.routes import collab_bp
    from app.knowledge.routes import knowledge_bp
    from app.manage.routes import manage_bp
    from app.networks.routes import networks_bp
    from app.assistant.routes import assistant_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp, url_prefix="/api/v1")
    app.register_blueprint(inventory_bp)
    app.register_blueprint(networks_bp)
    app.register_blueprint(knowledge_bp)
    app.register_blueprint(manage_bp)
    app.register_blueprint(collab_bp)
    app.register_blueprint(assistant_bp)

    # ───────── Logging ───────── #
    os.makedirs("logs", exist_ok=True)
    handler = RotatingFileHandler(
        "logs/helpdesk.log", maxBytes=10240, backupCount=10)
    handler.setLevel(app.config.get("LOG_LEVEL", "INFO"))
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    app.logger.addHandler(handler)

    if not any(isinstance(h, logging.StreamHandler) for h in app.logger.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(app.config.get("LOG_LEVEL", "INFO"))
        console_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        app.logger.addHandler(console_handler)

    app.logger.setLevel(app.config.get("LOG_LEVEL", "INFO"))
    app.logger.propagate = False

    if app.config.get("SQLALCHEMY_ECHO", False) or app.config.get("LOG_LEVEL", "INFO") == "DEBUG":
        sql_logger = logging.getLogger("sqlalchemy.engine")
        sql_logger.setLevel(logging.INFO)
        if not any(isinstance(h, logging.StreamHandler) for h in sql_logger.handlers):
            sql_console = logging.StreamHandler()
            sql_console.setFormatter(logging.Formatter("%(asctime)s [SQL] %(message)s"))
            sql_logger.addHandler(sql_console)
    app.logger.info("Helpdesk Pro started")

    # ───────── Root route ───────── #
    @app.route("/")
    def index():
        return render_template("index.html")

    return app
