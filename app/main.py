from __future__ import annotations
from dotenv import load_dotenv
from app.presentation.http.server import create_app

if __name__ == "__main__":
    load_dotenv()
    app = create_app()
    s = app.container.settings
    # use_reloader desliga o watchdog; threaded=False evita multiprocessing em /dev/shm
    # passthrough_errors=True evita debug PIN em ambientes restritos
    app.config["PROPAGATE_EXCEPTIONS"] = True
    app.run(
        host=s.app_host,
        port=s.app_port,
        debug=s.app_debug,
        use_reloader=False,
        threaded=False,
        passthrough_errors=True,
    )
