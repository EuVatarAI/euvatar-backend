from __future__ import annotations
from flask import Flask
from flask_cors import CORS

from app.core.container import Container
from app.presentation.http.blueprints.health_bp import bp as health_bp
from app.presentation.http.blueprints.session_bp import bp as session_bp
from app.presentation.http.blueprints.stt_bp import bp as stt_bp
from app.presentation.http.blueprints.context_bp import bp as context_bp
from app.presentation.http.blueprints.media_bp import bp as media_bp
from app.presentation.http.blueprints.training_bp import bp as training_bp
from app.presentation.http.auth import require_auth

def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.container = Container()  # type: ignore
    s = app.container.settings

    CORS(app, resources={r"/*": {"origins": s.cors_origins}})

    app.static_folder = s.static_dir
    app.static_url_path = ""

    app.register_blueprint(health_bp)
    app.register_blueprint(session_bp)
    app.register_blueprint(stt_bp)
    app.register_blueprint(context_bp)
    app.register_blueprint(media_bp)
    app.register_blueprint(training_bp)

    @app.before_request
    def _enforce_auth():
        # garante que todas as rotas passem pelo token compartilhado (exceto preflight)
        from flask import request
        if request.method != "OPTIONS":
            require_auth()

    return app
