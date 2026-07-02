from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler

# Pasta onde está este arquivo: /home/ubuntu/chats
BASE_DIR = Path(__file__).resolve().parent

# Cria /home/ubuntu/chats/logs caso não exista
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Arquivo que receberá apenas seus logs
LOG_FILE = LOG_DIR / "app.log"

# Variável que será importada pelo main.py
log = logging.getLogger("chatbot_log")
log.setLevel(logging.INFO)

# Não repassa para o logger padrão do Flask/Gunicorn
log.propagate = False

# Evita repetir handlers quando Gunicorn recarrega/importa o módulo
if not log.handlers:
    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8"
    )

    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s"
        )
    )

    log.addHandler(handler)