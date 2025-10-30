from __future__ import annotations
from flask import Flask
from flask_cors import CORS

from app.core.container import Container
from app.presentation.http.blueprints.health_bp import bp as health_bp
from app.presentation.http.blueprints.session_bp import bp as session_bp
from app.presentation.http.blueprints.stt_bp import bp as stt_bp
from app.presentation.http.blueprints.context_bp import bp as context_bp
from app.presentation.http.blueprints.media_bp import bp as media_bp
from app.presentation.http.blueprints.debug_bp import bp as debug_bp

def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    CORS(app)
    app.container = Container()  # type: ignore

    app.static_folder = app.container.settings.static_dir
    app.static_url_path = ""

    app.register_blueprint(health_bp)
    app.register_blueprint(session_bp)
    app.register_blueprint(stt_bp)
    app.register_blueprint(context_bp)
    app.register_blueprint(media_bp)
    app.register_blueprint(debug_bp)
    return app
