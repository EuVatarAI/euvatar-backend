"""Flask app factory and blueprint registration."""

from __future__ import annotations
import time
import uuid
from flask import Flask
from flask_cors import CORS
from flask import g, request

from app.core.container import Container
from app.presentation.http.blueprints.health_bp import bp as health_bp
from app.presentation.http.blueprints.session_bp import bp as session_bp
from app.presentation.http.blueprints.stt_bp import bp as stt_bp
from app.presentation.http.blueprints.context_bp import bp as context_bp
from app.presentation.http.blueprints.media_bp import bp as media_bp
from app.presentation.http.blueprints.training_bp import bp as training_bp
from app.presentation.http.blueprints.image_gen_bp import bp as image_gen_bp
from app.presentation.http.blueprints.quiz_bp import bp as quiz_bp
from app.presentation.http.auth import require_auth
from app.shared.setup_logger import LoggerManager
from app.shared.trace import set_trace_id


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.container = Container()  # type: ignore
    s = app.container.settings
    LoggerManager(debug=s.app_debug)

    CORS(
        app,
        resources={r"/*": {"origins": s.cors_origins}},
        allow_headers=[
            "Content-Type",
            "Authorization",
            "X-Client-Id",
            "X-Public-Avatar-Id",
        ],
        methods=["GET", "POST", "OPTIONS"],
    )

    app.static_folder = s.static_dir
    app.static_url_path = ""

    app.register_blueprint(health_bp)
    app.register_blueprint(session_bp)
    app.register_blueprint(stt_bp)
    app.register_blueprint(context_bp)
    app.register_blueprint(media_bp)
    app.register_blueprint(training_bp)
    app.register_blueprint(image_gen_bp)
    app.register_blueprint(quiz_bp)

    @app.before_request
    def _enforce_auth():
        trace_id = request.headers.get("X-Request-Id", "").strip() or str(uuid.uuid4())
        g.trace_id = trace_id
        g.request_started_at = time.time()
        set_trace_id(trace_id)
        app.logger.info(
            "[request] start method=%s path=%s", request.method, request.path
        )
        if request.method != "OPTIONS":
            require_auth()

    @app.after_request
    def _append_trace_id(response):
        response.headers["X-Request-Id"] = getattr(g, "trace_id", "-")
        elapsed_ms = int(
            (time.time() - getattr(g, "request_started_at", time.time())) * 1000
        )
        app.logger.info(
            "[request] end method=%s path=%s status=%s duration_ms=%s",
            request.method,
            request.path,
            response.status_code,
            elapsed_ms,
        )
        set_trace_id(None)
        return response

    return app
