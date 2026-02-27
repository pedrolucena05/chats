from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError
from sqlalchemy import func
import logging
from sqlalchemy.dialects.postgresql import insert

from dbConfig import db
from tableClasses import Message, Cliente
from guaranteedMax import enforce_max_users
from filelock import Timeout

MAX_MESSAGES_PER_NUMBER = 20

#LOG_FILE = "db_monitor.log"
#logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(threadName)s - %(message)s", handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")])
#logger = logging.getLogger(__name__)


def store_message(phone: str, content: str, direction: str, status: bool, respMan: int, notFlags: bool, name: str) -> Message:
    if not phone:
        raise ValueError("phone required")
    if direction not in ('in', 'out'):
        raise ValueError("direction must be 'in' or 'out'")

    phone_norm = phone.strip()
    if content is None:
        return

    session = db.session  # scoped_session do Flask-SQLAlchemy

    try:
        
        # --- caso principal: inserir mensagem (criar cliente se necessário) ---
        if notFlags:
            try:
                
                    # 1) garante que o cliente existe (sem corrida)
                    stmt = (
                        insert(Cliente)
                        .values(
                            phone=phone_norm,
                            user_name= name,
                            qtsMensagens=0,
                            respMan=int(respMan or 0),
                        )
                        .on_conflict_do_nothing(index_elements=[Cliente.phone])
                    )
                    session.execute(stmt)

                    # 2) carrega o cliente (agora ele existe)
                    cliente = session.get(Cliente, phone_norm)
                    if cliente is None:
                        raise RuntimeError("Cliente não encontrado após upsert (inesperado)")


                    # 4) insere mensagem
                    msg = Message(cliente_id=cliente.phone, direction=direction, content=content or "", status=status)
                    session.add(msg)
                    session.flush()
                    #logger.info("DEBUG: msg inserida id=%s", msg.id)

                    # 5) contador (opcional – dá pra otimizar depois)
                    cliente.qtsMensagens = (
                        session.query(func.count(Message.id))
                        .filter(Message.cliente_id == cliente.phone)
                        .scalar()
                    ) or 0

                    session.commit()

                    return msg

            except Exception:
                #logger.exception("Erro ao salvar mensagem")
                raise

        # --- else: apenas atualizar respManual e resps_order ---
        else:
            try:
                # Verifica existência (debug/log)
                cliente_exists = session.query(Cliente).filter_by(phone=phone_norm).first()
                #if not cliente_exists:
                    #logger.warning("store_message ELSE: nenhum cliente encontrado para phone=%s", phone_norm)
                    # opcional: criar o cliente em vez de retornar
                    # return None

                updated = session.query(Cliente).filter_by(phone=phone_norm).update(
                    {Cliente.respMan: int(respMan)},
                    synchronize_session=False
                )

                if updated:
                    session.commit()
                    #logger.debug("Cliente %s atualizado com respManual=%s resps_order=%s", phone_norm, respMan)
                else:
                    session.rollback()
                    #logger.warning("Nenhuma linha atualizada para phone=%s", phone_norm)

                return None

            except SQLAlchemyError:
                session.rollback()
                #logger.exception("Erro ao atualizar respMan/resps_order")
                raise

    except Timeout:
        #logger.exception("Timeout ao adquirir lock do DB")
        raise RuntimeError("Timeout ao tentar adquirir lock do DB")
    finally:
        session.close()
        # remove a sessão scoped para evitar sessões pendentes
        try:
            db.session.remove()
        except Exception:
            pass
            #logger.exception("Erro ao remover db.session no finally")