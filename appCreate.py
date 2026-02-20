import os
from flask import Flask
from dotenv import load_dotenv
from dbConfig import db  # seu db = SQLAlchemy()

def create_app(config_override: dict | None = None) -> Flask:
    load_dotenv()

    app = Flask(__name__, instance_relative_config=True)

    # config DB
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,                 # evita conexões “mortas”
        "connect_args": {"connect_timeout": 30}
    }

    if config_override:
        app.config.update(config_override)

    db.init_app(app)

    app.register_blueprint(db)

    # cria tabelas (opcional)
    with app.app_context():
        import tableClasses  # garante que models carreguem e registrem metadata
        db.create_all()

    return app