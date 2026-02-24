import tkinter as tk
from tkinter import ttk, simpledialog, messagebox, scrolledtext
from datetime import datetime
import threading
import os
import re
from urllib.parse import urlparse
import sys
import traceback
import logging
import inspect
import functools
import time, faulthandler
from sqlalchemy import func, desc
import unicodedata
from sqlalchemy.exc import SQLAlchemyError, OperationalError, DatabaseError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool
from filelock import FileLock, Timeout
from sqlalchemy import create_engine
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import requests


load_dotenv()

WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
DEFAULT_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v24.0")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
API_BASE = os.getenv("API_BASE", "https://SEU-DOMINIO.com/api")
API_KEY  = os.getenv("DASHBOARD_API_KEY", "SUA_CHAVE_AQUI")

# configuração
REFRESH_MS = 2000         # atualiza a cada 2s
MAX_SHOW_MESSAGES = 50    # quantas mensagens mostrar

incoming_cids = set()
incoming_lock = threading.Lock()


LOCK_TIMEOUT = 20
DB_RETRY_MAX = 15
DB_RETRY_DELAY = 0.2  # segundos



logger = logging.getLogger("chat_dashboard")
if not logger.handlers:
    fh = logging.FileHandler("dashboard_errors.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.setLevel(logging.DEBUG)


SESSION = requests.Session()
SESSION.headers.update({
    "X-API-Key": API_KEY,          # ajuste para o header que seu @require_api_key usa
    "Content-Type": "application/json",
    "Accept": "application/json",
})

def _url(path: str) -> str:
    return f"{API_BASE.rstrip('/')}/{path.lstrip('/')}"

def get_all_clients_http(self):
    r = SESSION.get(_url("/clients/with-last-ts"), timeout=15)
    r.raise_for_status()
    return r.json()

def get_latest_direction_for_phone(phone: str) -> str | None:
    r = SESSION.get(_url(f"/messages/{phone.strip()}/latest-direction"), timeout=10)
    r.raise_for_status()
    return r.json().get("direction")

def get_username_http(phone: str) -> str | None:
    phone = (phone or "").strip()
    r = SESSION.get(_url(f"/clients/{phone}/username"), timeout=10)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json().get("user_name")

def update_username_http(phone: str, user_name: str) -> bool:
    phone = (phone or "").strip()
    payload = {"user_name": user_name.strip()}

    r = SESSION.patch(
        _url(f"/clients/{phone}/username"),
        json=payload,
        timeout=10
    )

    if r.status_code == 404:
        return False

    r.raise_for_status()
    return bool(r.json().get("ok"))

def get_latest_messages_http(phone: str, limit: int = 20) -> dict:
    phone = (phone or "").strip()
    r = SESSION.get(_url(f"/clients/{phone}/messages/latest?limit={limit}"), timeout=15)
    if r.status_code == 404:
        return {"latest_id": 0, "messages": []}
    r.raise_for_status()
    return r.json()


    
# -------------------------
# util: roda Flask em thread
# -------------------------

def get_username_from_file(phone: str, file_path="clients.txt"):
    phone = phone.strip()

    if not phone:
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                parts = line.split(" , ", 1)
                if len(parts) != 2:
                    continue

                file_phone, user_name = parts

                if file_phone == phone:
                    return user_name.strip()

    except FileNotFoundError:
        return None

    return None

def save_client_if_not_exists(phone: str, user_name: str, file_path="clients.txt"):
    phone = phone.strip()
    user_name = (user_name or "").strip()

    if not user_name and phone:
        user_name = phone

    if not phone:
        return  # não grava telefone vazio

    # garante que o arquivo exista
    if not os.path.exists(file_path):
        open(file_path, "w", encoding="utf-8").close()

    existing_phones = set()

    # leitura do arquivo
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(" , ", 1)
            existing_phones.add(parts[0])

    # verifica se já existe
    if phone in existing_phones:
        return

    # escreve no final
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(f"{phone} , {user_name}\n")

def safe(fn):
    """Decorator para logar exceções com traceback e re-levantar."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            logger.debug("Entrando em %s", fn.__name__)
            return fn(*args, **kwargs)
        except Exception:
            exc_type, exc_val, exc_tb = sys.exc_info()
            tb = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
            logger.error("Exception em %s: %s\n%s", fn.__name__, exc_val, tb)
            # também grava num arquivo curto específico de exceções
            with open("dashboard_errors.log", "a", encoding="utf8") as f:
                f.write(f"\n[{datetime.utcnow().isoformat()}] Exception em {fn.__name__}: {exc_val}\n{tb}\n")
            raise
    return wrapper

# ---------------- watchdog: grava stacks se uma operação demorar ----------------
def dump_all_thread_traces(path="dashboard_hang.log"):
    """Escreve os stacks de todas as threads em 'path' (append)."""
    try:
        now = datetime.utcnow().isoformat()
        frames = sys._current_frames()
        with open(path, "a", encoding="utf8") as f:
            f.write(f"\n----- THREAD DUMP {now} -----\n")
            for thread in threading.enumerate():
                tid = thread.ident
                f.write(f"\n--- Thread {thread.name} id={tid} daemon={thread.daemon}\n")
                frame = frames.get(tid)
                if not frame:
                    f.write("  (no frame)\n")
                    continue
                for filename, lineno, name, line in traceback.extract_stack(frame):
                    f.write(f'  File "{filename}", line {lineno}, in {name}\n')
                    if line:
                        f.write(f'    {line.strip()}\n')
    except Exception:
        try:
            logger.exception("Erro ao dumpar thread stacks")
        except Exception:
            pass

class Watchdog:
    """Context manager / helper: dispara um timer que executa dump_all_thread_traces se o bloco demorar."""
    def __init__(self, timeout=5.0, path="dashboard_hang.log"):
        self.timeout = timeout
        self.path = path
        self._timer = None

    def _on_timeout(self):
        try:
            logger.error("Watchdog timeout: operação demorou mais de %ss. Dumping stacks...", self.timeout)
            dump_all_thread_traces(self.path)
        except Exception:
            pass

    def __enter__(self):
        self._timer = threading.Timer(self.timeout, self._on_timeout)
        self._timer.daemon = True
        self._timer.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._timer:
            self._timer.cancel()
            self._timer = None
        # não suprime exceções
        return False


# ---------- Helpers DB (usam flask_app.app_context()) ----------
def get_all_clients():
    """Retorna lista de clientes ordenada pelo último ts (mais recente primeiro)."""
    r = SESSION.get(_url("/clients"), timeout=15)
    r.raise_for_status()
    
    return r.json()  # lista de dicts

def get_messages_for_phone(phone, limit=20):
    """Retorna mensagens cronológicas asc para o phone."""
    phone = (phone or "").strip()
    if not phone:
        return []

    r = SESSION.get(_url(f"/messages/{phone}"), timeout=15)
    if r.status_code == 404:
        return []
    r.raise_for_status()

    msgs = r.json()  # lista de dicts (m.to_dict())
    if limit and len(msgs) > limit:
        msgs = msgs[-limit:]  # pega as últimas N mantendo ordem asc
    return msgs

def store_message_remote(phone: str, content: str, direction: str,
                         respMan: int = 0, resps_order: int = 0,
                         notFlags: bool = True, name: str = ""):
    if not phone:
        raise ValueError("phone required")
    if direction not in ("in", "out"):
        raise ValueError("direction must be 'in' or 'out'")

    payload = {
        "phone": phone.strip(),
        "content": content,
        "direction": direction,
        "respMan": int(respMan or 0),
        "resps_order": int(resps_order or 0),
        "notFlags": bool(notFlags),
        "name": name or "",
    }

    r = SESSION.post(_url("/store-message"), json=payload, timeout=20)
    r.raise_for_status()
    return r.json().get("message")  # dict ou None
   

@safe
def save_message_via_store(phone: str, content: str, direction: str, respMan: int, resps_order: int, notFlags: bool):
    
        if not phone:
            raise ValueError("phone required")
        if direction not in ('in', 'out', None):
            raise ValueError("direction must be 'in' or 'out'")

        saved_msg = None  # vamos retornar isso no final (se quiser)

        # 1) Salvar no banco (sem dar return aqui)

        if notFlags:
            saved_msg = store_message_remote(phone, content, direction, None, None, True)
        else:
            store_message_remote(phone, content, direction, respMan, resps_order, False)


        '''if saved_msg is None and notFlags:
            # fallback manual de insert
            for attempt in range(1, DB_RETRY_MAX + 1):
                session = Session()
                try:
                    cliente = session.query(Cliente).filter_by(phone=phone).first()
                    if not cliente:
                        cliente = Cliente(phone=phone, qtsMensagens=0)
                        session.add(cliente)
                        session.commit()

                    msg = Message(cliente_id=cliente.phone, direction=direction, content=content, ts=datetime.utcnow())
                    session.add(msg)
                    cliente.qtsMensagens = (cliente.qtsMensagens or 0) + 1
                    session.commit()
                    saved_msg = msg
                    break
                except Exception:
                    session.rollback()
                    raise
                finally:
                    session.close()'''

        '''if (saved_msg is None) and (notFlags is False):
            # fallback manual de update
            session = Session()
            try:
                cliente = session.query(Cliente).filter_by(phone=phone).first()
                if cliente:
                    cliente.respManual = int(respMan)
                    cliente.resps_order = int(resps_order)
                    session.commit()
            finally:
                session.close()'''

        # 2) Enviar pelo WhatsApp (só faz sentido quando direction == 'out' e notFlags == True)
        if direction == "out" and notFlags:
            if not WHATSAPP_ACCESS_TOKEN:
                raise RuntimeError("WHATSAPP_ACCESS_TOKEN não configurado")

            endpoint = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{DEFAULT_PHONE_NUMBER_ID}/messages"
            headers = {
                "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            }
            payload = {
                "messaging_product": "whatsapp",
                "to": "558199998295",
                "type": "text",
                "text": {"body": content},
            }

            resp = requests.post(endpoint, json=payload, headers=headers, timeout=10)
            # IMPORTANTÍSSIMO: logar a resposta real
            try:
                resp.raise_for_status()
            except Exception:
                logger.error("Falha WhatsApp %s: %s", resp.status_code, resp.text)
                raise

            logger.info("WhatsApp OK %s: %s", resp.status_code, resp.text)

        return saved_msg

def resp_reset_http(phone: str) -> bool:
    phone = (phone or "").strip()
    r = SESSION.patch(_url(f"/clients/{phone}/resp-reset"), timeout=10)

    if r.status_code == 404:
        return False
    if r.status_code == 409:
        # lock busy: você pode retry aqui se quiser
        return False

    r.raise_for_status()
    return bool(r.json().get("ok"))



# ---------- Tkinter UI ----------
class ChatDashboard(tk.Tk):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.report_callback_exception = lambda exc, val, tb: self._handle_uncaught_exception(exc, val, tb)
        threading.excepthook = lambda args: self._handle_uncaught_exception(args.exc_type, args.exc_value, args.exc_traceback, thread=args.thread)

        self.title("Chat Dashboard")
        self.geometry("1000x600")
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # === CORES (personalize aqui) ===
        bg_window = "#2b2b2b"        # fundo da janela
        left_bg = "#9d776d"          # fundo do painel da esquerda
        right_bg = "#9d776d"         # fundo do painel da direita
        text_bg = "#dcdcdc"          # fundo do painel de mensagens (ScrolledText)
        text_fg = "#282727"          # cor do texto no painel
        tree_bg = "#2b2b2b"          # fundo do treeview
        tree_fg = "#9d776d"
        self.text_bg = "#dcdcdc"
        # aplica cor de fundo da janela
        self.configure(bg=bg_window)

        self._state_lock = threading.Lock()
        self._pending_refresh = False

        self._do_refresh_running = False

        # === configurar estilo ttk (use 'clam' para permitir customizações) ===
        style = ttk.Style(self)
        try:
            style.theme_use('clam')
        except Exception:
            pass  # se tema não estiver disponível, segue do jeito que estiver
        
        button_bg = "#6b4b48"        # cor normal do botão
        button_fg = "#ffffff"        # texto do botão
        button_active = "#543831"    # quando hover/pressed

        # Estiliza frames/labels/buttons/treeview
        style.configure('Left.TFrame', background=left_bg)
        style.configure('Right.TFrame', background=right_bg)
        style.configure('TLabel', background=right_bg, foreground=text_fg)
        style.configure('TButton', padding=6)
        style.configure('TEntry', fieldbackground=text_bg, foreground=text_fg)

        # Layout (use ttk.Frame com estilo)
        self.left_frame = ttk.Frame(self, width=280, style='Left.TFrame')
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y)

        self.right_frame = ttk.Frame(self, style='Right.TFrame')
        self.right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        

        style.configure('Primary.TButton', background=button_bg, foreground=button_fg, padding=6, relief='flat')
        style.map('Primary.TButton', background=[('active', button_active), ('pressed', button_active)], foreground=[('disabled', '#888888')])
        style.configure('Secondary.TButton', background="#444444", foreground=button_fg, padding=4, relief='flat')
        style.map('Secondary.TButton', background=[('active', '#333333'), ('pressed', '#222222')])

        style.configure('Treeview', background=tree_bg, fieldbackground=tree_bg, foreground=tree_fg)
        #style.map('Treeview', background=[('selected', '#2563eb')], foreground=[('selected', '#ffffff')])
        
        # Estado
        self.status_var = None
        self.selected_phone = None
        self.refresh_job = None
        self._populating_clients = False
        self._suppress_selection_event = False
        self._pop_clients_running = False
        self._refresh_seq = 0
        self._auto_refresh_job = None            # handle do after()
        self._auto_refresh_interval = 2000      # 2000 ms = 2s (pode mudar)
        self._refresh_worker_running = False    # indica worker de mensagens em andamento
        self.resetMessage = tk.StringVar(value="")

        self._build_left()
        self._build_right()
        self._bind_keys()

        # inicializa list
        self.populate_clients()
        self.schedule_refresh()

        self._refresh_seq = 0           # versão/counter para resultados de refresh
        self._last_refresh_phone = None # opcional: última phone para qual foi feito refresh

        self.cont = 0

        self.respMan = []

        self.removeManualResp = False
        
    def update_resp_manual(phone_key, Session, max_attempts=10):
        attempt = 0
        while True:
            attempt += 1
            
            try:
                # bloqueia a linha para atualizar (falha imediatamente se já bloqueada)
                resp = resp_reset_http(phone_key)

                # remover de self.respMan aqui (faça fora deste método ou com lock)
                if resp:
                    return True

            except OperationalError as e:
                # Pode ser erro de lock (dependendo do DB) -> retry
                
                print(f"Tentativa {attempt} falhou por OperationalError para {repr(phone_key)}: {e}")

            except DatabaseError as e:
                # Verifique códigos específicos (Postgres: '40P01' deadlock, '40001' serialization failure)
                pgcode = getattr(getattr(e, 'orig', None), 'pgcode', None)
                
                print(f"Tentativa {attempt} falhou por DatabaseError (pgcode={pgcode}) para {repr(phone_key)}: {e}")

                # se não for um erro transiente, talvez queira abortar:
                # if pgcode not in ('40P01', '40001'): break

            except Exception as e:
                # erro inesperado
                
                print("Erro inesperado:", e)
                return False

            # retry controlado: backoff exponencial com jitter
            if attempt >= max_attempts:
                print(f"Esgotadas {max_attempts} tentativas para {repr(phone_key)}. Abortando.")
                return False
            sleep = (0.05 * (2 ** (attempt-1)))  # exponencial
            sleep = min(sleep, 2.0)
            time.sleep(sleep)

    def _install_exception_handlers(self):
        """Instala hooks para capturar exceções da UI, threads e excp não tratadas."""
        # 1) Tkinter callbacks (event handlers, command=...)
        #    O Tk chama report_callback_exception ao ocorrer exceção em callbacks.
        self.report_callback_exception = lambda exc, val, tb: self._handle_uncaught_exception(exc, val, tb)

        # 2) sys.excepthook para exceções não tratadas no thread principal
        sys.excepthook = lambda exc_type, exc_val, exc_tb: self._handle_uncaught_exception(exc_type, exc_val, exc_tb)

        # 3) threading.excepthook (Python 3.8+) para threads
        def _thread_hook(args):
            # args tem exc_type, exc_value, exc_traceback, thread
            self._handle_uncaught_exception(args.exc_type, args.exc_value, args.exc_traceback, thread=args.thread)
        threading.excepthook = _thread_hook

    def _handle_uncaught_exception(self, exc_type, exc_value, exc_tb, thread=None):
        """
        Centraliza tratamento: loga full traceback, extrai último frame para mostrar arquivo/linha/função,
        e mostra um messagebox (não bloqueante para threads).
        """
        try:
            tb_list = traceback.extract_tb(exc_tb) if exc_tb is not None else []
            # pega último frame relevante (se houver)
            last = tb_list[-1] if tb_list else None
            file_info = f"{last.filename}:{last.lineno} in {last.name}" if last else "sem frame disponível"
            short_line = last.line.strip() if last and last.line else ""

            # monta mensagem legível
            head_msg = f"Erro não tratado em {'thread '+thread.name if thread else 'main'}: {exc_type.__name__}: {exc_value}"
            loc_msg = f"Local: {file_info}\nCódigo: {short_line}"
            full_tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))

            # log completo em arquivo
            logger.error("%s\n%s\n%s", head_msg, loc_msg, full_tb)

            # mostra pop-up na UI (se estamos no main thread)
            def _show():
                try:
                    messagebox.showerror("Erro no Dashboard", f"{head_msg}\n\n{loc_msg}\n\nDetalhes em dashboard_errors.log")
                except Exception:
                    # se UI não estiver disponível, nada a fazer
                    pass

            # se estamos na thread principal do Tk, chamar direto; senão, agendar via after
            try:
                if threading.current_thread() is threading.main_thread():
                    _show()
                else:
                    # se self não existir (janela fechada) pode falhar; protege
                    try:
                        self.after(0, _show)
                    except Exception:
                        _show()
            except Exception:
                pass

        except Exception as e:
            # fallback se algo der errado no handler
            try:
                logger.exception("Erro dentro do handler de exceção: %s", e)
            except Exception:
                pass

    # ---------------- wrapper automático (opcional) ----------------
    @safe
    def _wrap_instance_methods_safe(self):
        """
        Envolve somente os métodos *definidos no mesmo módulo* da classe ChatDashboard,
        evitando métodos do Tkinter / builtins que quebram binding.
        Use apenas em DEBUG.
        """
        import inspect, functools, sys
        cls = self.__class__
        my_module = cls.__module__

        for name, func in list(inspect.getmembers(cls, predicate=inspect.isfunction)):
            # ignora métodos privados/dunder
            if name.startswith("_"):
                continue
            # ignora métodos que não são do mesmo módulo (evita tk internals)
            if getattr(func, "__module__", None) != my_module:
                continue

            # evita re-wrap
            bound_attr = getattr(self, name, None)
            if getattr(bound_attr, "__wrapped_by_safe__", False):
                continue

            # pega a função "crua" (não o método bound)
            original = func

            def make_wrapper(original_func):
                @functools.wraps(original_func)
                def wrapper(*args, **kwargs):
                    try:
                        # original_func é função da classe: será chamada com self como primeiro arg
                        return original_func(*args, **kwargs)
                    except Exception:
                        exc_type, exc_val, exc_tb = sys.exc_info()
                        # usa handler centralizado para log + popup
                        try:
                            self._handle_uncaught_exception(exc_type, exc_val, exc_tb)
                        except Exception:
                            pass
                        # re-levanta para manter comportamento natural (remova se quiser suprimir)
                        raise
                return wrapper

            wrapped = make_wrapper(original)
            # marca e atribui o wrapper ligado à instância (bind)
            try:
                wrapped.__wrapped_by_safe__ = True
                setattr(self, name, wrapped.__get__(self, cls))
            except Exception:
                # se não for possível sobrescrever, ignora
                pass

    
    def _build_left(self):
        lbl = ttk.Label(self.left_frame, text="", font=("Segoe UI", 12, "bold"))
        lbl.pack(padx=8, pady=(8,4), anchor=tk.W)

        # Search
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(self.left_frame, textvariable=self.search_var)
        search_entry.pack(fill=tk.X, padx=8)
        search_entry.bind("<KeyRelease>", lambda e: self.populate_clients())

        # --- container que ocupa todo o espaço restante do left_frame ---
        tree_frame = ttk.Frame(self.left_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Treeview clientes (sem height fixo para preencher o frame)
        cols = ("name")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("name", text="Nome")
        
        self.tree.column("name", width=260)
        
        self.tree.bind("<<TreeviewSelect>>", self.on_client_select)

        # Scrollbars
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)

        # conectar treeview às scrollbars
        self.tree.configure(yscrollcommand=vsb.set)

        # empacotar: tree preenchendo, barra vertical à direita, barra horizontal embaixo
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.LEFT, fill=tk.Y)

        # bottom buttons
        btn_frame = ttk.Frame(self.left_frame)
        btn_frame.pack(fill=tk.X, padx=8, pady=(0,8))

        # configurar tag para seleção persistente (cor clara)
        try:
            self.tree.tag_configure('selrow', background='#dcdcdc', foreground='#000000')
            self.tree.tag_configure('unanswered', background='#ffffff', foreground='#000000')
        except Exception:
            pass

        # --- Status (select options) na parte inferior ---
        status_frame = ttk.Frame(self.left_frame)
        status_frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        ttk.Label(status_frame).pack(side=tk.LEFT)

        
        status_options = (
            "Nenhum",
            "Bom Jesus",
            "Aurora Sábado",
            "Aurora Domingo",
            "Apipucos",
            "Lindu",
            "Igarassu",
        )

        # valor atual selecionado
        self.status_var = tk.StringVar(value=getattr(self, "selectedStatus", "Nenhum"))

        self.status_combo = ttk.Combobox(
            status_frame,
            textvariable=self.status_var,
            values=status_options,
            state="readonly"
        )
        self.status_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        # mantém a variável "oficial" atualizada
        def _on_status_change(event=None):
            self.selectedStatus = self.status_var.get()

        self.status_combo.bind("<<ComboboxSelected>>", _on_status_change)

        # garante que selectedStatus exista e reflita o valor inicial
        self.selectedStatus = self.status_var.get()

        # guarda o item anteriormente marcado (para remover a tag depois)
        self.prev_selected = None


    @safe
    def add_message_widget(self, ts: str, direction: str, content: str):
        """
        Cria uma 'bolha' de mensagem alinhada à esquerda (in) ou direita (out).
        """
        # Estilos/cores (ajuste conforme sua paleta)
        in_bg = "#f3f4f6"    # bolha do cliente (claro)
        in_fg = "#111827"
        out_bg = "#2563eb"   # bolha do operador (azul)
        out_fg = "#ffffff"

        # container para a bolha (usa sticky ao posicionar)
        row = ttk.Frame(self.msg_container)
        # cria label (tk.Label para controle total de cor)
        bubble = tk.Label(row, text=f"[{ts}] " + content, justify=tk.LEFT, wraplength=500,
                          padx=8, pady=6, bd=0, relief="flat", anchor="w")
        if direction == 'in':
            bubble.config(bg=in_bg, fg=in_fg)
            row.pack(fill=tk.X, anchor='w', pady=4, padx=8)
            bubble.pack(side=tk.LEFT, anchor='w')
        else:
            bubble.config(bg=out_bg, fg=out_fg)
            row.pack(fill=tk.X, anchor='e', pady=4, padx=8)
            bubble.pack(side=tk.RIGHT, anchor='e')

        # força atualização do canvas scrollregion
        self.msg_container.update_idletasks()
        self.msg_canvas.configure(scrollregion=self.msg_canvas.bbox("all"))
    @safe
    def _build_right(self):
        # header
        self.lbl_name = ttk.Label(self.right_frame, text="", font=("Segoe UI", 12, "bold"))
        # usaremos grid — posiciona o header na linha 0
        self.lbl_name.grid(row=0, column=0, columnspan=2, sticky='w', padx=8, pady=(8, 0))

        # configure grid weights: a linha 1 (onde fica o canvas) deve crescer
        self.right_frame.grid_rowconfigure(0, weight=0)  # header
        self.right_frame.grid_rowconfigure(1, weight=1)  # canvas (cresce)
        self.right_frame.grid_rowconfigure(2, weight=0)  # input (enviar)
        self.right_frame.grid_rowconfigure(3, weight=0)  # controls (atualizar/export)
        self.right_frame.grid_columnconfigure(0, weight=1)  # coluna principal
        self.right_frame.grid_columnconfigure(1, weight=0)  # coluna do scrollbar

        # === scrollable message area (Canvas + inner frame) ===
        self.msg_canvas = tk.Canvas(self.right_frame, borderwidth=0, highlightthickness=0, background=self.text_bg)

        self.msg_scrollbar = ttk.Scrollbar(self.right_frame, orient="vertical", command=self.msg_canvas.yview)
        self.msg_canvas.configure(yscrollcommand=self.msg_scrollbar.set)

        # place canvas and scrollbar using grid (canvas at row=1, col=0; scrollbar at col=1)
        self.msg_canvas.grid(row=1, column=0, sticky="nsew", padx=(8, 0), pady=8)
        self.msg_scrollbar.grid(row=1, column=1, sticky="ns", padx=(0, 4), pady=8)

        # inner frame where message widgets will be added
        self.msg_container = ttk.Frame(self.msg_canvas)
        self.msg_window = self.msg_canvas.create_window((0, 0), window=self.msg_container, anchor='nw')

        # configure inner frame resize behavior
        def _on_frame_configure(event):
            # update scroll region to match inner frame size
            self.msg_canvas.configure(scrollregion=self.msg_canvas.bbox("all"))

        self.msg_container.bind("<Configure>", _on_frame_configure)

        # resize inner frame width to canvas width
        def _on_canvas_resize(event):
            canvas_width = event.width
            self.msg_canvas.itemconfig(self.msg_window, width=canvas_width)

        self.msg_canvas.bind("<Configure>", _on_canvas_resize)

        # mouse wheel support (bind to canvas only, instead of bind_all)
        def _on_mousewheel(event):
            if hasattr(event, 'delta') and event.delta:  # Windows / Mac
                self.msg_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            else:  # Linux (event.num 4/5)
                if getattr(event, 'num', None) == 4:
                    self.msg_canvas.yview_scroll(-3, "units")
                elif getattr(event, 'num', None) == 5:
                    self.msg_canvas.yview_scroll(3, "units")

        # bind the wheel events to the canvas (safer)
        self.msg_canvas.bind("<MouseWheel>", _on_mousewheel)
        self.msg_canvas.bind("<Button-4>", _on_mousewheel)
        self.msg_canvas.bind("<Button-5>", _on_mousewheel)

        # === bottom input area (row 2) ===
        bottom = ttk.Frame(self.right_frame)
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=(8, 4))

        self.entry_var = tk.StringVar()
        self.entry = ttk.Entry(bottom, textvariable=self.entry_var, style='TEntry')
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.entry.bind("<Return>", lambda e: self.send_message())

        ttk.Button(bottom, text="Enviar", command=self.send_message, style='Primary.TButton').pack(side=tk.LEFT)

        # controls: refresh / export + botão de "novas mensagens" (row 3)
        ctrl = ttk.Frame(self.right_frame)
        ctrl.grid(row=3, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))

        # left side controls
        left_controls = ttk.Frame(ctrl)
        left_controls.pack(side=tk.LEFT)
        ttk.Button(left_controls, text="Reset", command=lambda: self.refresh_current(self.selected_phone), style='Secondary.TButton').pack(side=tk.LEFT)
        #ttk.Button(left_controls, text="Exportar (JSON)", command=self.export_current, style='Secondary.TButton').pack(side=tk.LEFT, padx=(8,0))
        tk.Label(left_controls, textvariable=self.resetMessage,fg='red', font=("Segoe UI", 10)).pack(side=tk.LEFT, padx=(8,0))

        # right side: new messages button (starts hidden)
        right_controls = ttk.Frame(ctrl)
        right_controls.pack(side=tk.RIGHT)
        self.new_msg_count = 0
        self.btn_new_messages = ttk.Button(right_controls, text="", command=self.goto_end, style='Primary.TButton')
        self.btn_new_messages.pack(side=tk.RIGHT)
        self.btn_new_messages.pack_forget()  # hide until needed

        # detect scroll clicks to maybe hide new-msg button
        # bind to canvas (not bind_all) so other widgets aren't affected
        self.msg_canvas.bind("<Button-1>", lambda e: self._maybe_hide_newmsg_button())
        self.msg_canvas.bind("<MouseWheel>", lambda e: self._maybe_hide_newmsg_button())
        self.msg_canvas.bind("<ButtonRelease-1>", lambda e: self._maybe_hide_newmsg_button())

        # track last message id visto para a seleção atual
        self.last_message_id = None

    @safe
    def start_auto_refresh(self):
        """Inicia o agendador periódico (idempotente)."""
        if self._auto_refresh_job is None:
            # dispara o primeiro tick imediatamente ou com pequeno delay
            self._auto_refresh_job = self.after(self._auto_refresh_interval, self._auto_refresh_tick)

    @safe
    def stop_auto_refresh(self):
        """Cancela o agendador."""
        if self._auto_refresh_job is not None:
            try:
                self.after_cancel(self._auto_refresh_job)
            except Exception:
                pass
            self._auto_refresh_job = None

    @safe
    def _auto_refresh_tick(self):
        """
        Tick executado pelo tkinter.mainloop a cada self._auto_refresh_interval ms.
        Só dispara refresh_current se NÃO houver workers de clients ou de messages rodando.
        """
        try:
            # se algum worker estiver em execução, pulamos este tick
            if getattr(self, "_pop_clients_running", False):
                # limpa e agenda o próximo tick
                self._auto_refresh_job = self.after(self._auto_refresh_interval, self._auto_refresh_tick)
                return
            if getattr(self, "_refresh_worker_running", False):
                # há um worker de mensagens em andamento -> pula
                self._auto_refresh_job = self.after(self._auto_refresh_interval, self._auto_refresh_tick)
                return

            # nada rodando -> chama a função que dispara os workers
            try:
                # use after(0, ...) para rodar no loop principal (mas ele é chamado aqui já no mainloop)
                self.refresh_current()
            except Exception:
                # não queremos que uma exceção quebre o agendador
                pass
        finally:
            # agenda o próximo tick (mesmo se refresh_current levantou)
            self._auto_refresh_job = self.after(self._auto_refresh_interval, self._auto_refresh_tick)


    
    '''def _get_sqlite_path_from_flask_config():
        """Retorna caminho absoluto do arquivo sqlite usado pelo SQLAlchemy do flask_app, ou None."""
        uri = flask_app.config.get('SQLALCHEMY_DATABASE_URI') or ''
        if not uri:
            return None
        # suporta 'sqlite:///relative/path.db' e 'sqlite:////absolute/path.db'
        if uri.startswith('sqlite:///') or uri.startswith('sqlite:////'):
            # remove prefix
            path = uri.split('sqlite:///')[-1]
            # se for caminho relativo (ex: chat.db), torna absoluto relativo ao cwd do app
            if not os.path.isabs(path):
                # tentar basear no flask_app.root_path
                base = getattr(flask_app, 'root_path', os.getcwd())
                path = os.path.abspath(os.path.join(base, path))
            return path
        # fallback: tentar extrair via urlparse
        parsed = urlparse(uri)
        if parsed.scheme == 'sqlite':
            return parsed.path
        return None'''
    
    @safe
    def _maybe_hide_newmsg_button(self):
        try:
            f, l = self.msg_canvas.yview()
            if l >= 0.995:
                self.new_msg_count = 0
                self.btn_new_messages.pack_forget()
        except Exception:
            pass
    
    @safe
    def get_latest_message_id_for_phone(phone: str) -> int:
        r = SESSION.get(_url(f"/messages/{phone.strip()}/latest-id"), timeout=10)
        r.raise_for_status()
        return int(r.json().get("latest_id") or 0)

    @safe
    def _bind_keys(self):
        self.bind("<Control-r>", lambda e: self.populate_clients())


    @safe
    def _apply_clients(self, rows_serial, q_filter, prev_selected):
        """
        Aplica o resultado serializado no Treeview (rodando na UI thread).
        Não marca _pop_clients_running aqui — isso é responsabilidade de populate_clients/_on_populate_done.
        """
        # NOTA: NÃO mudar _pop_clients_running aqui no início.
        try:
            # suprime handler de seleção enquanto atualiza
            self._populating_clients = True
            self._suppress_selection_event = True

            # copia local e rápida do incoming_cids (segura o lock só aqui)
            try:
                incoming_lock
            except NameError:
                local_incoming = set(incoming_cids)
            else:
                with incoming_lock:
                    local_incoming = set(incoming_cids)

            # limpa tree atual
            for i in self.tree.get_children():
                self.tree.delete(i)

            # normalize prev_selected: se caller não passou prev_selected, use o estado atual
            if prev_selected is None:
                prev_selected = getattr(self, "selected_phone", None) or getattr(self, "prev_selected", None)
            if prev_selected is not None:
                prev_selected = str(prev_selected)

            # re-insere linhas filtrando por q_filter (se houver)
            q = (q_filter or '').lower()
            for user_name, phone in rows_serial:
                if q and q not in (phone or "").lower():
                    continue

                phone_key = str(phone)
                cid_key = str(phone) if phone is not None else None

                tags = ()

                if cid_key in local_incoming or phone_key in local_incoming:
                    tags = ('unanswered',)
                
                if prev_selected is not None and phone_key == prev_selected:
                    tags = ('selrow',)

                self.tree.insert("", "end", iid=phone_key, values=(user_name, phone_key), tags=tags)

            # restaura seleção/foco se necessário
            if prev_selected and prev_selected in self.tree.get_children():
                try:
                    self.tree.selection_set(prev_selected)
                    self.tree.focus(prev_selected)
                    self.prev_selected = prev_selected
                except Exception:
                    pass

            # ajuste dinâmico do mapa de seleção do Treeview
            sel = self.tree.selection()
            any_unanswered_selected = any(
                'unanswered' in (self.tree.item(iid, 'tags') or ())
                for iid in sel
            )

            style = ttk.Style()
            if any_unanswered_selected:
                style.map('Treeview',
                        background=[('selected', '#f2f2f2')],
                        foreground=[('selected', '#000000')])
            # (se quiser restaurar o mapa padrão, descomente e ajuste abaixo)
            # else:
            #     style.map('Treeview',
            #               background=[('selected', '#2563eb')],
            #               foreground=[('selected', '#ffffff')])

        finally:
            # libera flags de UI
            self._suppress_selection_event = False
            self._populating_clients = False

            # --- CLEANUP: sinaliza que o populate atual terminou e trata pending ---
            # faça isso sob lock para evitar races com populate_clients()
            with self._state_lock:
                self._pop_clients_running = False
                pending = getattr(self, "_pending_populate", False)
                self._pending_populate = False

            if pending:
                # reagendar novo populate (pequeno atraso evita reentrância imediata)
                self.after(50, self.populate_clients)



    @safe
    def _on_populate_done(self, rows_serial, q_filter, prev_selected):
        """
        Roda na UI thread: aplica os rows_serial no tree e faz o cleanup de estado
        (limpa _pop_clients_running e dispara pending se necessário).
        """
        try:
            if self.resetMessage.get() != "":
                self.cont += 1
                if self.cont == 2:
                    self.cont = 0
                    self.resetMessage.set("")
            # chama a função que atualiza o Treeview (já existente)
            self.update_client_status()
            self._apply_clients(rows_serial, q_filter, prev_selected)
        finally:
            # Cleanup/pendings devem ser feitos sob lock
            with self._state_lock:
                self._pop_clients_running = False
                self._pending_populate = False


        
    @safe
    def _populate_worker(self, q=None, current=None):
        """
        Worker: roda fora da UI thread. Faz a query ao DB via Session (thread-safe)
        e serializa uma lista de tuplas (cid, phone, qts, last_ts) para aplicar depois.
        q and current são opcionais (podem ser None).
        """
        rows_serial = []
        try:
            session = Session()
            try:
                rows = get_all_clients_http()

                rows = [[d["phone"], d["qtsMensagens"], d["last_ts"], d["user_name"]] for d in rows]

                for r in rows:
                    phone = str(r[0]) if r[0] is not None else ''

                    qts = int(r[1]) if r[1] is not None else 0
                    last_ts = str(r[2]) if r[2] is not None else None
                    rows_serial.append((r[-1], phone))
                    user_name = r[-1]
                    print (user_name)
                    print (self.status_var.get())
                    save_client_if_not_exists(phone, user_name)

                    direction =  get_latest_direction_for_phone(phone)

                    cid_key = str(phone) if phone is not None else None
                    if direction == 'in':
                        with incoming_lock:
                            if cid_key is not None:
                                incoming_cids.add(cid_key)
                    else:
                        with incoming_lock:
                            if cid_key is not None:
                                incoming_cids.discard(cid_key)

                    if self.removeManualResp:
                        phoneSelected = self.respMan[0]
                        self.removeManualResp = False
                        print("telefone selecionado")
                        print(phoneSelected)

                        phoneSelected = re.sub(r'\D', '', str(phoneSelected))
                        print(f"Novo fone: {phoneSelected}")

                        del self.respMan[0]

                        #store_message(phoneSelected, None, None, 0, 0, True)
                        


            finally:
                session.close()
        except Exception as e:
            logger.exception("populate_worker error: %s", e)

        # Agenda aplicação na UI thread (sempre use after para evitar tocar widgets fora da main thread)
        try:
            # se você tiver uma função _on_populate_done, use-a; se não, chame _apply_clients diretamente via after
            self.after(0, lambda: self._on_populate_done(rows_serial, q, current))
        except Exception:
            # janela pode estar fechada; ignore
            pass

  
    @safe
    def populate_clients(self, q_filter=None, prev_selected=None):
        """
        Inicia o processo de popular clientes. Se já estiver rodando,
        marca pending e retorna (debounce).
        """
        # rápido check e marcação atômica
        with self._state_lock:
            if self._pop_clients_running:
                self._pending_populate = True
                return
            self._pop_clients_running = True

        # inicia worker que fará o fetch (worker roda fora da UI thread)
        t = threading.Thread(target=self._populate_worker, args=(q_filter, prev_selected), daemon=True)
        t.start()

    def update_client_status(self):
        status = self.status_var.get()
        phone = self.selected_phone

        if status == "Nenhum" and phone:
            try:
                statuses = {"Bom Jesus", "Aurora Sábado", "Aurora Domingo", "Apipucos", "Lindu", "Igarassu"}
                
                    
                    
                current_name = get_username_http(phone)
                
                if current_name:
                    current_name = current_name.split("     (")
                
                if current_name and len(current_name) > 1 and current_name[-1].endswith(")") and any(status in current_name[-1] for status in statuses):
                    current_name = current_name[0]
                    updated = update_username_http(phone, current_name)

                            



            except SQLAlchemyError as e:
                print(e)
                

        
        elif phone:
            try:
                
                new_name = get_username_from_file(phone)
                new_name = new_name + f"     ({self.status_var.get()})"
                updated = update_username_http(phone, current_name)

            except SQLAlchemyError as e:
                
                print("Erro ao atualizar status:", e)

    @safe
    def on_client_select(self, event):
        # se estamos suprimindo eventos (populate_clients) ignoramos
        if getattr(self, '_suppress_selection_event', False):
            return

        statuses = {"Bom Jesus", "Aurora Sábado", "Aurora Domingo", "Apipucos", "Lindu", "Igarassu"}
        # protege contra reentrada (marca logo no começo)
        self._suppress_selection_event = True

        current_name = None

        try:
            sel = self.tree.selection()
            if not sel:
                return
            phone = sel[0]

            current_name = get_username_http(phone)

            
            if current_name:
                current_name = current_name.split("     (")

                if len(current_name) > 1 and current_name[-1].endswith(")") and any(status in current_name[-1] for status in statuses):
                    self.status_var.set(current_name[-1][:-1])
        
            else: 
                self.status_var.set("Nenhum")

            

            # se clicou no mesmo cliente, apenas reafirma seleção/foco
            if phone == self.selected_phone:
                try:
                    # ao reafirmar, não queremos reentrar porque a flag está True
                    self.tree.selection_set(phone)
                    self.tree.focus(phone)
                except Exception:
                    pass
                return

            # remove marcação anterior (se houver)
            prev = getattr(self, 'prev_selected', None)
            if prev:
                try:
                    tags = list(self.tree.item(prev, 'tags') or ())
                    if 'selrow' in tags:
                        tags.remove('selrow')
                        self.tree.item(prev, tags=tags)
                except Exception:
                    pass

            # define novo selecionado e marca no treeview
            self.selected_phone = phone
            self.prev_selected = phone

            user_name = get_username_from_file(phone)

            
            self.update_client_status()


            try:
                tags = list(self.tree.item(phone, 'tags') or ())
                if 'selrow' not in tags:
                    tags.append('selrow')
                    self.tree.item(phone, tags=tags)
                # estas chamadas não irão reentrar pois a flag está True
                self.tree.selection_set(phone)
                self.tree.focus(phone)
            except Exception:
                pass
            
            normalizedPhone = f"+55 {self.selected_phone[2]}{self.selected_phone[3]} {self.selected_phone[3:]}"
            
            # atualiza label
            self.lbl_name.config(text=f"{user_name} ({normalizedPhone})")

            # limpa imediatamente o container (remove mensagens do cliente anterior)
            for w in list(self.msg_container.winfo_children()):
                try:
                    w.destroy()
                except Exception:
                    pass

            # reseta estado de controle de novas mensagens / last id
            self.new_msg_count = 0
            try:
                self.btn_new_messages.pack_forget()
            except Exception:
                pass

            # zera o last_message_id para forçar leitura completa do DB deste cliente
            self.last_message_id = None

            # chame o refresh com pequeno atraso para evitar corrida com populate/selection
            try:
                # disparar com after evita condições de corrida; o worker fará o resto
                self.after(20, lambda: self.refresh_messages(force=True))
            except Exception:
                self.refresh_messages(force=True)
        finally:
            # libera a flag só após terminar todo o trabalho (importante)
            # também colocamos um pequeno after para garantir que event handlers
            # que vieram logo em seguida não reentrem
            def _unset():
                try:
                    self._suppress_selection_event = False
                except Exception:
                    pass
            # libera com pequeno atraso (10ms) — evita reentrância imediata
            self.after(10, _unset)
        


    @safe
    def refresh_messages(self, force=False):
        """
        Inicia um worker thread para buscar mensagens. Não bloqueia a GUI.
        Usa um contador (self._refresh_seq) para invalidar resultados antigos.

        Nota: se `_apply_clients` estiver rodando, marca `_pending_refresh = True`
        e retorna — o refresh será disparado depois (veja instruções abaixo).
        """

        # garante que existe um lock de estado (cria se necessário)
        if not hasattr(self, "_state_lock"):
            self._state_lock = threading.Lock()

        # se chamado fora da main thread, reagenda para UI thread
        if threading.current_thread() is not threading.main_thread():
            try:
                self.after(0, lambda: self.refresh_messages(force=force))
            except Exception:
                # não conseguimos agendar na UI thread — aborta
                return
            return

        # ---- checagens iniciais que você já tinha ----
        if not self.selected_phone:
            # limpa se não houver telefone selecionado
            for w in self.msg_container.winfo_children():
                w.destroy()
            return

        try:
            first_frac, last_frac = self.msg_canvas.yview()
        except Exception:
            first_frac, last_frac = (0.0, 1.0)
        user_at_bottom = last_frac >= 0.995

        # snapshot do telefone e último id
        phone = self.selected_phone
        prev_last = self.last_message_id

        # ---- proteção / protocolo de concorrência ----
        with self._state_lock:
            # se _apply_clients está rodando, guarda pending e retorna
            if getattr(self, "_pop_clients_running", False):
                self._pending_refresh = True
                return

            # marca que um worker de refresh vai rodar
            self._refresh_worker_running = True

            # incrementa seq de forma atômica
            self._refresh_seq = getattr(self, "_refresh_seq", 0) + 1
            my_seq = self._refresh_seq

            # guarda telefone da última requisição
            self._last_refresh_phone = phone

        # ---- começa o thread worker (mantendo seu comportamento original) ----
        t = threading.Thread(
            target=self._refresh_worker,
            args=(phone, force, user_at_bottom, prev_last, my_seq),
            daemon=True
        )
        t.start()




    # --- worker que roda em thread separada ---
    @safe
    def _refresh_worker(self, phone, force, user_at_bottom, prev_last, seq):
        """
        Worker seguro que cria/fecha sessão por thread e serializa mensagens
        como lista de dicts. Ao terminar, agenda _apply_messages no thread UI,
        passando a mesma 'seq' (versão).
        """
        msgs = []
        latest_id = 0
        try:

            session = Session()
            try:
                resp = get_latest_messages_http(phone, 20)
                qmsgs = resp.get("messages", [])
                qmsgs = [[m["id"], m["ts"], m["direction"], m["content"]]for m in qmsgs]
                qmsgs.reverse()
                for m in qmsgs:
                    msgs.append({
                        'id': m[0],
                        'ts': m[1],
                        'direction': m[2],
                        'content': m[3]
                    })
            finally:
                session.close()
        except Exception as e:
            # não deixe o worker explodir; log para debug
            print("worker error using Session:", e)

        # agenda a aplicação dos dados no thread principal
        # passamos 'seq' para permitir verificação de validade
        try:
            self.after(0, lambda: self._apply_messages(phone, msgs, latest_id, force, user_at_bottom, prev_last, seq))
        except Exception:
            # se a janela foi fechada e after falhar, apenas ignore
            pass


    # --- apply: atualiza a UI (só no main thread) ---
    @safe
    def _apply_messages(self, phone, msgs, latest_id, force, user_at_bottom, prev_last, seq):
        """
        Atualiza a UI com os dados 'msgs'. Ignora resultados cuja 'seq' seja
        menor que o atual (tornou-se obsoleto).
        """
        # Se já houve chamadas mais novas, ignora este resultado
        if seq != getattr(self, "_refresh_seq", None):
            # resultado obsoleto
            return

        # se o usuário já mudou de cliente, ignora
        if phone != self.selected_phone:
            return

        children = self.msg_container.winfo_children()

        # append-only se usuário estiver no fim, já houver children e não for force
        if user_at_bottom and children and not force:
            new_msgs = []
            if prev_last:
                for m in msgs:
                    if m['id'] > (prev_last or 0):
                        new_msgs.append(m)
            else:
                # sem prev_last -> append tudo (pode ocorrer no primeiro load)
                new_msgs = msgs

            for m in new_msgs:
                self.add_message_widget(m['ts'], m['direction'], m['content'])

            self.last_message_id = latest_id
            try:
                self.msg_canvas.update_idletasks()
                self.msg_canvas.yview_moveto(1.0)
            except Exception:
                pass

            self.new_msg_count = 0
            try:
                self.btn_new_messages.pack_forget()
            except Exception:
                pass
            return

        # caso contrário: rebuild completo
        for w in self.msg_container.winfo_children():
            w.destroy()

        for m in msgs:
            self.add_message_widget(m['ts'], m['direction'], m['content'])

        self.last_message_id = latest_id

        if user_at_bottom or force:
            try:
                self.msg_canvas.update_idletasks()
                self.msg_canvas.yview_moveto(1.0)
            except Exception:
                pass
            self.new_msg_count = 0
            try:
                self.btn_new_messages.pack_forget()
            except Exception:
                pass
        else:
            # fallback: move para topo (ou tente restaurar posição)
            try:
                self.msg_canvas.yview_moveto(0.0)
            except Exception:
                pass
    
    @safe
    def goto_end(self):
        """Força atualização e rola ao fim (chamado ao clicar 'Novas mensagens')."""
        self.refresh_messages(force=True)
        try:
            self.msg_canvas.update_idletasks()
            self.msg_canvas.yview_moveto(1.0)
        except Exception:
            pass
        self.new_msg_count = 0
        try:
            self.btn_new_messages.pack_forget()
        except Exception:
            pass

    @safe
    def send_message(self):
        text = self.entry_var.get().strip()
        if not text:
            return
        if not self.selected_phone:
            messagebox.showwarning("Aviso", "Selecione um cliente antes de enviar.")
            return

        try:
            save_message_via_store(self.selected_phone, text, 'out', None, None, True)
        except Exception as e:
            messagebox.showerror("Erro ao salvar", str(e))
            return

        # ao enviar, queremos atualizar imediatamente (você está no fim por provável ação do usuário)
        # força refresh e rola ao fim

        self.entry_var.set("")
        # Força atualização para ver a mensagem enviada e a possível resposta
        self.refresh_messages(force=True)

    @safe
    def refresh_current(self, phone):
        aux = []
        aux.append(self.selected_phone)
        self.respMan.append(aux)
        print(self.respMan)
        self.removeManualResp = True
        save_message_via_store(phone, "", "out", 0, 0, False)
        self.resetMessage.set("Reset Realizado com sucesso")
        
    


    @safe
    def export_current(self):
        if not self.selected_phone:
            messagebox.showwarning("Aviso", "Selecione um cliente para exportar.")
            return
        msgs = get_messages_for_phone(self.selected_phone, limit=10000)
        import json
        data = [ { "id": m.id, "direction": m.direction, "content": m.content, "ts": m.ts.isoformat() } for m in msgs ]
        path = f"export_{self.selected_phone}.json"
        with open(path, "w", encoding="utf8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        messagebox.showinfo("Exportado", f"Exportado {len(data)} mensagens para {path}")



    @safe
    def schedule_refresh(self):
        """
        Agenda a primeira execução de _do_refresh em 2s se nada estiver rodando.
        Depois disso _do_refresh será responsável por reagendar a si mesmo
        ao terminar (garantindo execução sequencial).
        """
        # se já houver um job agendado, cancela (evita enfileiramento antigo)
        if getattr(self, "refresh_job", None):
            try:
                self.after_cancel(self.refresh_job)
            except Exception:
                pass
            self.refresh_job = None

        # Se _do_refresh já estiver rodando, a execução pendente será agendada
        # automaticamente quando ele terminar (via _pending_refresh). Então só
        # agende o primeiro disparo se nada estiver rodando agora.
        with self._state_lock:
            if self._do_refresh_running:
                # marca pending para garantir nova execução depois do término
                self._pending_refresh = True
                return

        # agenda a primeira execução em 2000 ms
        self.refresh_job = self.after(2000, self._do_refresh)

    @safe
    def _do_refresh(self):
        """
        Executa um ciclo de refresh (populate_clients + refresh_messages).
        Garante não-reentrância e, ao terminar, agenda a próxima execução.
        """
        # Protege a entrada para evitar reentrância
        with self._state_lock:
            if self._do_refresh_running:
                # já está rodando — apenas marque pending e saia
                self._pending_refresh = True
                return
            self._do_refresh_running = True

        try:
            # ----- Aqui vai o trabalho real do refresh -----
            # Chame suas rotinas (essas chamadas devem ser seguras - não bloqueantes na UI)
            try:
                self.refresh_messages()
                self.populate_clients()
            except Exception:
                # opcional: log do erro para não esconder exceções
                logger.exception("Erro durante _do_refresh")
            # -----------------------------------------------
        finally:
            # marca fim de execução e decide quando reagendar
            with self._state_lock:
                self._do_refresh_running = False
                pending = self._pending_refresh
                self._pending_refresh = False

            # Se houver pending (alguém pediu refresh enquanto estávamos rodando),
            # reagende rápido; senão, agende o ciclo normal.
            # Use after(0, ...) para reagendar imediatamente (ou um leve delay).
            if pending:
                # reagenda quase imediatamente (pouco delay para evitar spin)
                self.refresh_job = self.after(100, self._do_refresh)
            else:
                self.refresh_job = self.after(2000, self._do_refresh)


    @safe
    def on_close(self):
        
        if self.refresh_job:
            self.after_cancel(self.refresh_job)
        
        self.destroy()

# ---------- rodar ----------
if __name__ == "__main__":
    
    gui = ChatDashboard()
    gui.mainloop()


