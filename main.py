import threading
import argparse
from datetime import datetime
import os
from os.path import join
import logging
import time
import queue
import random
import requests
from dotenv import load_dotenv
from functools import wraps

from flask import request, jsonify, current_app, Blueprint
from sqlalchemy import event
from sqlalchemy.exc import OperationalError, DatabaseError

from filelock import FileLock

from clientResponse import respClient
from databaseWrite import store_message
from dbConfig import db
from appCreate import create_app
from databaseRead import clientStatus

from tableClasses import Message, Cliente
from sqlalchemy import func, desc


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
#LOG_FILE = os.path.join(BASE_DIR, "app.log")

'''logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ],
    force=True
)'''

#log = logging.getLogger("bot")
#log.setLevel(logging.INFO)
#log.info("Logger OK. Escrevendo em: %s", LOG_FILE)

# App initalizer
app = create_app()


# 
# DATABASE CONFIG
#
instance_folder = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'instance')
os.makedirs(instance_folder, exist_ok=True)

load_dotenv()

WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
DEFAULT_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v24.0")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")

    
MAX_MESSAGES_PER_NUMBER = 20
MAX_USERS = 600      

WORKER_IDLE_TIMEOUT = int(os.getenv("WORKER_IDLE_TIMEOUT", 10 * 60))  # segundos

# Retry config (exponencial)
RETRY_MAX_ATTEMPTS = int(os.getenv("RETRY_MAX_ATTEMPTS", 5))
RETRY_BASE_DELAY = float(os.getenv("RETRY_BASE_DELAY", 0.5))  # segundos
RETRY_MAX_DELAY = float(os.getenv("RETRY_MAX_DELAY", 20.0))  # cap do delay

workers = {}  # number -> worker dict
workers_lock = threading.Lock()


def send_whatsapp_message(phone_number_id: str, to: str, text: str) -> dict:
    """
    Envia texto via WhatsApp Cloud API (POST /{phone_number_id}/messages).
    Lança requests.HTTPError em erros.
    """
    if not WHATSAPP_ACCESS_TOKEN:
        raise RuntimeError("WHATSAPP_ACCESS_TOKEN não configurado")

    #log.info("Dentro da funlçao de envio")

    endpoint = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }
    resp = requests.post(endpoint, json=payload, headers=headers, timeout=10)
    resp.raise_for_status()

    #log.info("Função de envio finalizada com sucesso (dentro da função)")
    return resp.json()


DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")

def require_api_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-API-Key", "")
        if not DASHBOARD_API_KEY or key != DASHBOARD_API_KEY:
            return jsonify({"error": "unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper

def send_whatsapp_with_retry(phone_number_id: str, to: str, text: str, max_attempts: int = RETRY_MAX_ATTEMPTS, base_delay: float = RETRY_BASE_DELAY, max_delay: float = RETRY_MAX_DELAY) -> bool:
    """
    Tenta enviar com retry exponencial + jitter.
    Retorna True se enviado com sucesso; False se falhou após tentativas.
    """
    attempt = 0

    if text == "" or text == None:
        return True
    while attempt < max_attempts:
        try:
            resp = send_whatsapp_message(phone_number_id, "558199998295", text)
            #log.info(f"Função de envio finalizada com sucesso ({resp})")
            return True
        except Exception as e:
            attempt += 1
            # cálculo exponencial com cap e jitter
            exp = (2 ** (attempt - 1)) * base_delay
            delay = min(exp, max_delay)
            # jitter: +/- 0.5*delay
            jitter = random.uniform(-0.5 * delay, 0.5 * delay)
            sleep_time = max(0.0, delay + jitter)
            #urrent_app.logger.warning(f"Envio falhou (attempt {attempt}/{max_attempts}) para {to}: {e}. Retry em {sleep_time:.2f}s")
            #log.info(f"Envio falhou (attempt {attempt}/{max_attempts}) para {to}: {e}. Retry em {sleep_time:.2f}s")
            #print(f"Envio falhou (attempt {attempt}/{max_attempts}) para {to}: {e}. Retry em {sleep_time:.2f}s")
            time.sleep(sleep_time)
    current_app.logger.error(f"Falha ao enviar mensagem para {to} após {max_attempts} tentativas.")
    #log.info(f"Envio falhou (attempt {attempt}/{max_attempts}) para {to}: {e}. Retry em {sleep_time:.2f}s")
    #print(f"Envio falhou (attempt {attempt}/{max_attempts}) para {to}: {e}. Retry em {sleep_time:.2f}s")
    return False


def start_worker_if_missing(number: str, user_name: str):
    """
    Cria e inicia um worker (thread + queue + state) caso não exista ou esteja morto.
    """
    with workers_lock:
        w = workers.get(number)
        if w and w.get("thread") and w["thread"].is_alive():
            return w
        # criar novo worker
        q = queue.Queue()
        state = {"respMan": None, "lastIn": None}
        t = threading.Thread(target=worker_loop, args=(number, q, state, user_name), name=f"worker-{number}", daemon=True)
        worker = {"thread": t, "queue": q, "state": state, "last_active": time.time()}
        workers[number] = worker
        t.start()
        return worker


def worker_loop(number: str, q: queue.Queue, state: dict, user_name: str):
    """
    Loop que roda dentro da thread do worker.
    Reproduz o comportamento do terminal_loop: inicializa clientStatus, gera mensagem inicial,
    processa itens da fila sequencialmente, chama respClient, store_message e envia resposta via Cloud API com retry.
    """
    global lock
    '''with app.app_context():
        
        try:
            state["respMan"], state["respOrder"], state["lastIn"] = clientStatus(number)
        except Exception:
            current_app.logger.exception("Erro em clientStatus na inicialização do worker")
            state["respMan"], state["respOrder"], state["lastIn"] = 0, 0, ""'''



    # PROCESSAMENTO CONTÍNUO
    while True:
        try:
            item = q.get(timeout=1.0)
        except queue.Empty:
            # verifica inatividade para finalizar worker
            if time.time() - workers[number]["last_active"] > WORKER_IDLE_TIMEOUT:
                current_app.logger.info(f"Worker {number} inativo por {WORKER_IDLE_TIMEOUT}s — finalizando.")
                break
            continue

        if item is None:
            # sinal para despertar/stop (opcional)
            continue

        text = item.strip()
        workers[number]["last_active"] = time.time()

        # fluxo normal: salvar entrada, atualizar status, chamar respClient, salvar resposta e enviar via API
        with app.app_context():
            

            try:
                state["lastIn"], msgs, state["respMan"] = clientStatus(number)
            except Exception:
                state["lastIn"], msgs = "", None, None
                #log.info("Erro em clientStatus durante processamento (worker)")

            #log.info(f"Worker {number} Antes do respClient: Resp Order: Resp man: {state['respMan']}")
            respMan = state["respMan"]
            if respMan == 0:
                try:
                    reply , status, state["respMan"] = respClient(text, msgs)
                except Exception:
                    current_app.logger.exception("Erro em respClient (worker)")
                    reply = "Desculpe, ocorreu um erro ao processar sua mensagem."

                current_app.logger.debug(f"Worker {number} Depois do respClient: lastIn: {state['lastIn']}")

                try:
                    store_message(number, text, 'in', status, respMan, True, user_name)
                except Exception:
                    current_app.logger.exception("Erro ao salvar resposta (worker)")

                try:
                    store_message(number, reply, 'out', status, respMan, True, user_name)
                except Exception:
                    current_app.logger.exception("Erro ao salvar resposta (worker)")

                try:
                    store_message(number, reply, 'out', status, respMan, False, user_name)
                except Exception:
                    current_app.logger.exception("Erro ao salvar resposta (worker)")

                # envio via WhatsApp Cloud API com retry exponencial
                phone_number_id = DEFAULT_PHONE_NUMBER_ID or None
                if not phone_number_id:
                    current_app.logger.warning("PHONE_NUMBER_ID não definido; não será enviado via Cloud API")
                else:
                    try:
                        ok = send_whatsapp_with_retry(phone_number_id, number, reply)
                        if not ok:
                            current_app.logger.error(f"Não foi possível enviar resposta para {number} após tentativas.")
                    except Exception:
                        current_app.logger.exception("Exceção inesperada ao tentar enviar via WhatsApp Cloud API")

    # remover worker do mapa (cleanup)
    with workers_lock:
        w = workers.get(number)
        if w and w.get("thread") and w["thread"].ident == threading.get_ident():
            # se for o mesmo objeto/thread, remova
            del workers[number]
    current_app.logger.info(f"Worker {number} finalizado.")




@app.patch("/clients/<phone>/username")
@require_api_key
def update_client_username(phone):
    phone = (phone or "").strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400

    data = request.get_json(force=True) or {}
    current_name = (data.get("user_name") or "").strip()

    if not current_name:
        return jsonify({"error": "user_name required"}), 400

    updated = (
        db.session.query(Cliente)
        .filter(Cliente.phone == phone)
        .update({Cliente.user_name: current_name}, synchronize_session=False)
    )

    if not updated:
        db.session.rollback()
        return jsonify({"error": "cliente_not_found"}), 404

    db.session.commit()

    return jsonify({
        "ok": True,
        "phone": phone,
        "user_name": current_name
    })

from sqlalchemy import desc

MAX_SHOW_MESSAGES = 20  # ou use o mesmo valor que você usa no dashboard

@app.get("/clients/<phone>/messages/latest")
@require_api_key
def get_latest_messages_for_client(phone):
    phone = (phone or "").strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400

    # (opcional) permitir que o dashboard escolha o limite via querystring
    limit = request.args.get("limit", None)
    try:
        limit = int(limit) if limit is not None else MAX_SHOW_MESSAGES
    except ValueError:
        return jsonify({"error": "limit must be int"}), 400
    limit = max(1, min(limit, 300))  # trava segurança

    cliente = db.session.query(Cliente).filter(Cliente.phone == phone).first()
    if not cliente:
        return jsonify({"error": "cliente_not_found", "latest_id": 0, "messages": []}), 404

    # última mensagem (para pegar latest_id)
    last = (
        db.session.query(Message.id)
        .filter(Message.cliente_id == cliente.phone)
        .order_by(desc(Message.ts), desc(Message.id))
        .first()
    )
    latest_id = int(last[0]) if last else 0

    # últimas N mensagens
    qmsgs = (
        db.session.query(Message)
        .filter(Message.cliente_id == cliente.phone)
        .order_by(desc(Message.ts), desc(Message.id))
        .limit(limit)
        .all()
    )

    return jsonify({
        "phone": cliente.phone,
        "latest_id": latest_id,
        "messages": [m.to_dict() for m in qmsgs]  # mantém ordem desc como sua query
    })

@app.get("/clients")
@require_api_key
def list_clients():
    # Lista clientes com last_ts
    rows = (
        db.session.query(
            Cliente.phone,
            Cliente.user_name,
            Cliente.qtsMensagens,
            getattr(Cliente, "status", None),  # se não existir, vira None
            func.max(Message.ts).label("last_ts"),
        )
        .outerjoin(Message, Message.cliente_id == Cliente.phone)
        .group_by(Cliente.phone, Cliente.user_name, Cliente.qtsMensagens, getattr(Cliente, "status", None))
        .order_by(desc("last_ts"))
        .all()
    )

    out = []
    for phone, user_name, qts, status, last_ts in rows:
        out.append({
            "phone": phone,
            "user_name": user_name,
            "qts": int(qts or 0),
            "status": status,
            "last_ts": last_ts.isoformat() if last_ts else None
        })
    return jsonify(out)

@app.get("/clients/<phone>/username")
@require_api_key
def get_client_username(phone):
    phone = (phone or "").strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400

    user_name = (
        db.session.query(Cliente.user_name)
        .filter(Cliente.phone == phone)
        .scalar()
    )

    if user_name is None:
        return jsonify({"error": "cliente_not_found"}), 404

    return jsonify({"phone": phone, "user_name": user_name})

@app.patch("/clients/<phone>/resp-reset")
@require_api_key
def resp_reset(phone):
    phone_key = (phone or "").strip()
    if not phone_key:
        return jsonify({"error": "phone required"}), 400

    try:
        cliente = (
            db.session.query(Cliente)
            .filter(Cliente.phone == phone_key)
            .with_for_update(nowait=True)  # ou skip_locked=True
            .one_or_none()
        )

        if cliente is None:
            db.session.rollback()
            return jsonify({"error": "cliente_not_found"}), 404

        cliente.respMan = 0
        

        db.session.commit()
        return jsonify({"ok": True, "phone": phone_key, "respManual": 0})

    except OperationalError as e:
        # normalmente é lock nowait / busy
        db.session.rollback()
        return jsonify({"error": "lock_busy", "detail": str(e)}), 409

    except DatabaseError as e:
        db.session.rollback()
        pgcode = getattr(getattr(e, "orig", None), "pgcode", None)
        return jsonify({"error": "db_error", "pgcode": pgcode, "detail": str(e)}), 500

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "unexpected_error", "detail": str(e)}), 500

@app.get("/messages/<phone>")
@require_api_key
def list_messages(phone):
    phone = phone.strip()
    msgs = (
        db.session.query(Message)
        .filter(Message.cliente_id == phone)
        .order_by(Message.ts.asc(), Message.id.asc())
        .limit(300)
        .all()
    )
    return jsonify([m.to_dict() for m in msgs])

@app.patch("/clients/<phone>/status")
@require_api_key
def update_status(phone):
    phone = phone.strip()
    data = request.get_json(force=True) or {}
    status = (data.get("status") or "Nenhum").strip()

    # Se você tiver coluna Cliente.status, atualize aqui
    if not hasattr(Cliente, "status"):
        return jsonify({"error": "Cliente.status não existe no modelo"}), 400

    updated = (
        db.session.query(Cliente)
        .filter(Cliente.phone == phone)
        .update({Cliente.status: status}, synchronize_session=False)
    )
    if not updated:
        db.session.rollback()
        return jsonify({"error": "cliente_not_found"}), 404

    db.session.commit()
    return jsonify({"ok": True, "phone": phone, "status": status})

@app.post("/messages")
@require_api_key
def send_message_from_dashboard():
    """
    Tkinter manda: { "to": "55...", "text": "..." }
    Opcional: também salva no DB.
    """
    data = request.get_json(force=True) or {}
    to = (data.get("to") or "").strip()
    text = (data.get("text") or "").strip()

    if not to or not text:
        return jsonify({"error": "to/text required"}), 400

    # salva no banco (out)
    store_message(to, text, "out", True, respMan=0, notFlags=True)

    # envia via WhatsApp (se você quiser)
    phone_number_id = DEFAULT_PHONE_NUMBER_ID
    ok = send_whatsapp_with_retry(phone_number_id, to, text)

    return jsonify({"ok": bool(ok)})

@app.get("/messages/<phone>/latest-id")
@require_api_key
def get_latest_message_id(phone):
    phone = (phone or "").strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400

    # (opcional) valida se cliente existe
    cliente = db.session.query(Cliente).filter(Cliente.phone == phone).first()
    if not cliente:
        return jsonify({"phone": phone, "latest_id": 0})

    last = (
        db.session.query(Message.id)
        .filter(Message.cliente_id == phone)  # ou == cliente.phone
        .order_by(desc(Message.ts), desc(Message.id))
        .first()
    )

    latest_id = int(last[0]) if last else 0
    return jsonify({"phone": phone, "latest_id": latest_id})

@app.get("/clients/with-last-ts")
@require_api_key
def clients_with_last_ts():
    rows = (
        db.session.query(
            Cliente.phone,
            Cliente.qtsMensagens,
            func.max(Message.ts).label("last_ts"),
            Cliente.user_name,
        )
        .outerjoin(Message, Message.cliente_id == Cliente.phone)
        .group_by(Cliente.phone, Cliente.qtsMensagens, Cliente.user_name)
        .order_by(desc("last_ts"))
        .all()
    )

    out = []
    for phone, qtsMensagens, last_ts, user_name in rows:
        out.append({
            "phone": phone,
            "qtsMensagens": int(qtsMensagens or 0),
            "last_ts": last_ts.isoformat() if last_ts else None,
            "user_name": user_name,
        })

    return jsonify(out)

@app.get("/messages/<phone>/latest-direction")
@require_api_key
def get_latest_direction(phone):
    phone = (phone or "").strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400

    direction = (
        db.session.query(Message.direction)
        .filter(Message.cliente_id == phone)
        .order_by(Message.ts.desc(), Message.id.desc())
        .limit(1)
        .scalar()
    )

    return jsonify({
        "phone": phone,
        "direction": direction  # "in", "out" ou None
    })

@app.get("/clients/<phone>/respman")
@require_api_key
def get_respman(phone):
    phone = (phone or "").strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400

    respMan = (
        db.session.query(Cliente.respMan)
        .filter(Cliente.phone == phone)
        .scalar()
    )

    if respMan is None:
        return jsonify({"error": "cliente_not_found"}), 404

    return jsonify({"phone": phone, "respMan": int(respMan or 0)})

@app.post("/store-message")
@require_api_key
def api_store_message():
    data = request.get_json(force=True) or {}

    phone = (data.get("phone") or "").strip()
    content = data.get("content")
    direction = (data.get("direction") or "").strip()
    respMan = data.get("respMan", 0)
    resps_order = data.get("resps_order", 0)
    notFlags = bool(data.get("notFlags", True))
    name = (data.get("name") or "").strip()

    if not phone:
        return jsonify({"error": "phone required"}), 400
    if direction not in ("in", "out"):
        return jsonify({"error": "direction must be 'in' or 'out'"}), 400
    if content is None:
        return jsonify({"ok": True, "message": None})

    # REUSA sua função do servidor (a que você já tem no backend)
    msg = store_message(phone=phone, content=str(content), direction=direction, status = True, respMan=int(respMan or 0), notFlags=notFlags, name=name)

    return jsonify({
        "ok": True,
        "message": msg.to_dict() if msg else None
    })

@app.route("/bot", methods=["GET", "POST"])
def webhook_handler():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        return "Forbidden", 403

    # POST: parse payload
    payload = request.get_json(silent=True) or {}
    phone = None
    text = None
    phone_number_id = None
    userName = None

    #log.info("------------------ NOVA REQUISICAO -------------------")

    try:
        entry = payload.get("entry") or payload.get("entries") or []
        if entry:
            change = entry[0].get("changes", [{}])[0]
            value = change.get("value", {})

            contacts = value.get("contacts") or []
            if not contacts:
                # fallback: alguns payloads colocam contacts dentro da mensagem
                messages = value.get("messages", [])
                if messages:
                    contacts = messages[0].get("contacts") or []
                

            if contacts:
                userName = contacts[0].get("profile", {}).get("name")
                if userName:
                    userName = userName.strip()  # opcional: limpar espaços

                #log.info(f"Nome do Remetente: {userName}")

            phone_number_id = value.get("metadata", {}).get("phone_number_id") or DEFAULT_PHONE_NUMBER_ID
            messages = value.get("messages", [])
            if messages:
                msg = messages[0]
                phone = msg.get("from") or msg.get("wa_id")
                if msg.get("type") == "text":
                    text = msg.get("text", {}).get("body")
                else:
                    send_whatsapp_with_retry(phone_number_id, phone, "Mande apenas texto por favor, estamos usando assistente virtual")

            #log.info(f"ID: {phone_number_id}")
            #log.info(f"Mensagem: {msg}")
            #log.info(f"Phone Number: {phone}")
            #log.info(f"TExto: {text}")

            if userName:
                pass
                
            else:
                userName = phone

    

    except Exception:
        current_app.logger.exception("Erro ao parsear payload webhook")

    # fallbacks
    if not phone:
        if "from" in payload:
            phone = payload.get("from")
    if "text" in payload and text is None:
        tx = payload.get("text")
        text = tx.get("body") if isinstance(tx, dict) else str(tx)

    if not phone or text is None:
        current_app.logger.warning("Webhook sem número ou texto; ignorando")
        return jsonify({"status": "ignored"}), 200

    # garante criação do worker e enfileira
    worker = start_worker_if_missing(phone, userName)
    worker["queue"].put(text)
    worker["last_active"] = time.time()

    return jsonify({"status": "queued"}), 200


def terminal_loop():
    print("=== Simulação em terminal iniciada ===")
    print("Digite 'exit' para sair. Para reiniciar diálogo com outro número digite '!novo' (sem aspas).")
    current_number = input("Número do cliente (ex: 5511999999999): ").strip()
    if not current_number:
        print("Número inválido. Saindo.")
        return
    print("Iniciando conversa com:", current_number)
    lastIn, msgs, respMan = clientStatus(current_number)
    # show initial prompt (call respClient with empty to generate menu)
    reply , status, respMan = respClient("ola", msgs)
    # armazena apenas a resposta inicial (não armazenamos mensagem 'vazia' recebida)
    with app.app_context():
        try:
            store_message(current_number, reply, 'in', status, respMan, True, "Paulo")
        except Exception:
            app.logger.exception("erro ao salvar resposta inicial")

    print (lastIn)
    print("Bot:", reply)

    while True:
        try:
            user = input("Você: ").strip()
            print("\n\n")
        except (KeyboardInterrupt, EOFError):
            print("\nSaindo...")
            break

        if user.lower() in ('exit', 'sair', 'quit'):
            print("Encerrando simulação.")
            break

        # salva mensagem do usuário e resposta do bot (dentro do app context)
        with app.app_context():
            try:
                store_message(current_number, reply, 'in', status, respMan, True, "Paulo")
            except Exception:
                app.logger.exception("erro ao salvar mensagem recebida terminal")
            lastIn, msgs, respMan = clientStatus(current_number)

            print("Antes do respClient")
            
            print (f"Resp man: {respMan}")

            reply , status, respMan = respClient(user, msgs)

            print("\n\nDepois do resp client")
            print (f"Resp man: {respMan}")
            print("last in: ", lastIn)
            print("Bot:", reply)

            try:
                store_message(current_number, reply, 'in', status, respMan, True, "Paulo")
            except Exception:
                app.logger.exception("erro ao salvar resposta terminal")


def is_db_locked_sqlite(engine) -> bool:
    conn = engine.raw_connection()  # raw para executar SQL SQLite direto
    try:
        # Tenta iniciar transação que exige lock de escrita
        conn.execute("BEGIN IMMEDIATE")
        # se chegou aqui, obteve lock — desfaz e libera
        conn.rollback()
        return False  # NÃO está bloqueado
    except OperationalError as e:
        msg = str(e).lower()
        if "database is locked" in msg:
            return True   # está bloqueado
        raise
    finally:
        conn.close()



    
# -------------------------
# util: roda Flask em thread
# -------------------------
def run_flask_in_thread(host='0.0.0.0', port=5000):
    def _run():
        # use_reloader=False para evitar execução dupla na thread
        app.run(host=host, port=port, debug=False, use_reloader=False)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t


# -------------------------
# main
# -------------------------
if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('--server-only', action='store_true', help='executa apenas o servidor Flask (sem terminal)')
    parser.add_argument('--host', default='0.0.0.0', help='host Flask (default 0.0.0.0)')
    parser.add_argument('--port', type=int, default=5000, help='porta Flask (default 5000)')
    args = parser.parse_args()


    # cria as tabelas caso não existam
    with app.app_context():
        db.create_all()
        # garante que cada nova conexão defina PRAGMAs essenciais


    run_flask_in_thread(host=args.host, port=args.port)
    print(f"Flask rodando em http://{args.host}:{args.port} (em background)")


    #terminal_loop()
    

    try:
        while True:
            pass
    except KeyboardInterrupt:
        print("Servidor finalizado.")