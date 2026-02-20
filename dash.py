from main import app
from tableClasses import Message, Cliente

with app.app_context():
    msgs = Message.query.all()
    for m in msgs:
        print(m.to_dict())

    clients = Cliente.query.all()
    for c in clients:
        print (c.to_dict())