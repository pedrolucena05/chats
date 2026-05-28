import os
import requests
from sqlalchemy import update
from tableClasses import Cliente
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
DEFAULT_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v24.0")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

session = SessionLocal()

phones = (session.query(Cliente.phone).filter(Cliente.templateNeeded == True).all())

phones = [phone for (phone,) in phones]

url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{DEFAULT_PHONE_NUMBER_ID}/messages"

headers = {
    "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
    "Content-Type": "application/json"
}

for phone in phones:
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": "reativar_a_conversa",
            "language": {
                "code": "pt_BR"
            }
        }
    }

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code in [200, 201]:
        stmt = (
            update(Cliente)
            .where(Cliente.phone == phone)
            .values(templateNeeded=False)
        )

        session.execute(stmt)

session.commit()