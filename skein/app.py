"""Flask app factory."""

from __future__ import annotations

from flask import Flask, g

from .config import Config
from .dashboard.routes import bp as dashboard_bp
from .db import open_db
from .ingest.routes import bp as ingest_bp


def create_app(config: Config | None = None, *, db_conn=None) -> Flask:
    """Create the Skein Flask app.

    `db_conn` is for tests — when provided, every request reuses it instead of
    opening a fresh per-request connection.
    """
    cfg = config or Config.load("./config.json")
    app = Flask(__name__)
    app.config["SKEIN_CONFIG"] = cfg
    app.config["SKEIN_SHARED_DB"] = db_conn

    if db_conn is None:
        # Eagerly initialize schema so the first request doesn't race.
        open_db(cfg.db_path).close()

    @app.teardown_appcontext
    def _close_db(_exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    app.register_blueprint(ingest_bp)
    app.register_blueprint(dashboard_bp)
    return app


def main() -> None:
    cfg = Config.load("./config.json")
    app = create_app(cfg)
    app.run(host=cfg.host, port=cfg.port, debug=False)


if __name__ == "__main__":
    main()
