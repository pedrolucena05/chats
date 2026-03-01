from dbConfig import db
from tableClasses import Message, Cliente

from sqlalchemy import func, desc
from sqlalchemy.exc import SQLAlchemyError

MAX_USERS = 600

def enforce_max_users():
    """
    Garante que a quantidade de telefones distintos COM MENSAGENS não ultrapasse MAX_USERS.
    Se ultrapassar, apaga todas as mensagens dos telefones mais recentemente ativos
    até reduzir o total para MAX_USERS.
    """
    # Conta clientes distintos que possuem pelo menos uma mensagem
    total_clients_with_msgs = (
        db.session.query(func.count(func.distinct(Message.cliente_id))).scalar() or 0
    )

    
    if total_clients_with_msgs <= MAX_USERS:
        return

    to_remove = total_clients_with_msgs - MAX_USERS

    # Seleciona os 'to_remove' cliente_ids mais recentemente ativos (ordenados por último ts desc)
    recent_clients = (
        db.session.query(Message.cliente_id, func.max(Message.ts).label('last_ts'))
        .group_by(Message.cliente_id)
        .order_by(desc('last_ts'))
        .limit(to_remove)
        .all()
    )
    cliente_ids = [row.cliente_id for row in recent_clients]

    if not cliente_ids:
        return

    try:
        # Deleta todas as mensagens desses clientes
        db.session.query(Message).filter(Message.cliente_id.in_(cliente_ids)).delete(synchronize_session=False)
        db.session.commit()

        # Atualiza qtsMensagens dos clientes afetados para 0 (já que apagamos as mensagens)
        db.session.query(Cliente).filter(Cliente.phone.in_(cliente_ids)).update(
            {Cliente.qtsMensagens: 0}, synchronize_session=False
        )
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()