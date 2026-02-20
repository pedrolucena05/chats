import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from datetime import datetime
from dotenv import load_dotenv

# carrega .env
load_dotenv()

# app Flask mínimo
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# model de teste simples
class Cliente(db.Model):
    __tablename__ = "cliente"

    #id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(40), nullable=False, unique=True, index=True, primary_key=True)
    user_name = db.Column(db.String(40), nullable= True, default = None)
    qtsMensagens = db.Column(db.Integer, default=0, nullable=False)
    respManual = db.Column(db.Integer, nullable=False, default=0)
    resps_order = db.Column(db.Integer, default=0, nullable=False)

    messages = db.relationship(
        "Message",
        back_populates="cliente",
        cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {"phone": self.phone, "UserName": self.user_name, "qtsMensagens": self.qtsMensagens, "respManual": self.respManual, "resps_order": self.resps_order}


class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(40), db.ForeignKey('cliente.phone'), nullable=False)
    direction = db.Column(db.String(4), nullable=False)  # 'in' ou 'out'
    content = db.Column(db.Text, nullable=False)
    ts = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), nullable=False, index=True)

    cliente = db.relationship("Cliente", back_populates="messages")

    def to_dict(self):
        return {
            "id": self.id,
            "cliente_id": self.cliente_id,
            "direction": self.direction,
            "content": self.content,
            "ts": self.ts.isoformat()
        }

with app.app_context():
    print("🔌 Testando conexão com o banco...")

    # testa conexão pura
    try:
        db.session.execute(text("SELECT 1"))
        print("✅ Conexão com PostgreSQL OK")
    except Exception as e:
        print("❌ Falha na conexão")
        raise e

    print("📦 Criando tabela (se não existir)...")
    db.create_all()


