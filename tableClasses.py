from dbConfig import db
from datetime import datetime

class Cliente(db.Model):
    __tablename__ = "cliente"

    #id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(40), nullable=False, unique=True, index=True, primary_key=True)
    user_name = db.Column(db.String(40), nullable= True, default = None)
    qtsMensagens = db.Column(db.Integer, default=0, nullable=False)
    respMan = db.Column(db.Integer, default=0, nullable=False)

    messages = db.relationship(
        "Message",
        back_populates="cliente",
        cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {"phone": self.phone, "UserName": self.user_name, "qtsMensagens": self.qtsMensagens, "respManual": self.respMan}


class Message(db.Model):
    __tablename__ = "messages"
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.String(40), db.ForeignKey('cliente.phone'), nullable=False)
    direction = db.Column(db.String(4), nullable=False)  # 'in' ou 'out'
    content = db.Column(db.Text, nullable=False)
    ts = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), nullable=False, index=True)
    status = db.Column(db.Boolean, nullable= True, default = None)

    cliente = db.relationship("Cliente", back_populates="messages")

    def to_dict(self):
        return {
            "id": self.id,
            "cliente_id": self.cliente_id,
            "direction": self.direction,
            "content": self.content,
            "ts": self.ts.isoformat(),
            "status": self.status
        }