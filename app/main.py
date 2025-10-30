from __future__ import annotations
from dotenv import load_dotenv
from app.presentation.http.server import create_app

if __name__ == "__main__":
    load_dotenv()
    app = create_app()
    s = app.container.settings
    app.run(host=s.app_host, port=s.app_port, debug=s.app_debug)
