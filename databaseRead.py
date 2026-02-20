from tableClasses import Cliente, Message
from dbConfig import db
from appCreate import create_app

def clientStatus(phoneIntern):
    phoneIntern = str(phoneIntern)

    app = create_app()
    
    with app.app_context():
        session = db.session 
        try:

            respMan = None
            respOrder = None
            cliente = session.get(Cliente, phoneIntern)

            if cliente:
                respMan = cliente.respManual
                respOrder = cliente.resps_order

            else:
                respMan = 0
                respOrder = 0



            last = (session.query(Message).filter(Message.cliente_id == phoneIntern,Message.direction == 'in').order_by(Message.ts.desc(), Message.id.desc()).first())
            
            if last is not None:
                last = last.content

            else:
                last = ""

            if cliente:
                respMan = cliente.respManual
                respOrder = cliente.resps_order

            else:
                respMan = 0
                respOrder = 0

            print (f"Last in function: {last}")
            # resp pode ser True/False/None
            return respMan, respOrder, last
        except Exception as e:
            print(f"Erro ao buscar respManual para {phoneIntern}: {e}")
            return 0, 0, 0
        finally:
            try:
                session.close()
            except Exception:
                pass