import re
import os
import requests

GRAPH_API_VERSION = "v24.0"
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "EAASd8rQNZCFQBQoZCgVZBdaK7NLxh4016txHzznjjW21uzFHgsliq9KJCXz4ZAgZAeZC2vZBw8tMf59enft6NKkgPqedsWV04wtWMgV1uqILpl9K8QrtWGTjBbusHTNWQrMY6lZCV0dIu7H0EDUWKwv6PpSFy5o3E9SvpX092wiBFbldoF96IQRuGguqEq9UMnchpx21wkA4KkiIauScPPhdqLeZCUIqAwYfxRpZCsuYwSRQ2HMZBT4EUDhLKcb22bRY2Jxeale4qp0ZBFoCMsMWcrZAcZBTnKl2u81KlZBgxm9bAZDZD")

def normalize_e164(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if not (8 <= len(digits) <= 15):
        raise ValueError("Número com tamanho inesperado: " + digits)
    return digits

def send_whatsapp_text(sender_phone_id: str, to: str, text: str):
    #to = normalize_e164(to_number)   # ex: "+1 555 169 5445" -> "15551695445"
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{sender_phone_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    r = requests.post(url, json=payload, headers=headers)
    try:
        r.raise_for_status()
    except requests.HTTPError:
        # imprime erro legível
        print("Erro HTTP:", r.status_code, r.text)
        raise
    return r.json()

while True:
    msg = input("Mensagem: ")
    response = send_whatsapp_text("768653469671697", "558183373310", msg)
    print(response)

