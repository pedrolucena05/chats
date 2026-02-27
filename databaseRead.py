from tableClasses import Cliente, Message
from dbConfig import db
from appCreate import create_app

def clientStatus(phoneIntern):
    phoneIntern = str(phoneIntern)

    app = create_app()
    
    with app.app_context():
        session = db.session 
        try:
            respMan = False
            
            cliente = session.get(Cliente, phoneIntern)

            if cliente:
                respMan = cliente.respMan

            else:
                respMan = 0

            msgs = (
                session.query(Message)
                .filter(Message.cliente_id == phoneIntern)
                .order_by(Message.ts.desc(), Message.id.desc())  
                .all()
            )

            msgsList = []

            for m in msgs:
                if m.status is False:
                    msgsList.append(m.content)  # <- aqui
                else:
                    break

            # Se quiser na ordem cronológica (antiga → nova)
            msgsList.reverse()

            last = (session.query(Message).filter(Message.cliente_id == phoneIntern,Message.direction == 'in').order_by(Message.ts.desc(), Message.id.desc()).first())
            
            if last is not None:
                last = last.content

            else:
                last = ""


            # resp pode ser True/False/None
            return last, msgsList, respMan
        except Exception as e:
            return None, None, None
        finally:
            try:
                session.close()
            except Exception:
                pass