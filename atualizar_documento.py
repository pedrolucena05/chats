import os
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

api_key = os.getenv("OPENAI_API_KEY")
vector_store_id = "vs_6a4619a48bcc81919f1017b18e8d56a2"

if not api_key:
    raise RuntimeError("OPENAI_API_KEY não encontrada no .env")

if not vector_store_id:
    raise RuntimeError("OPENAI_VECTOR_STORE_ID não encontrada no .env")

client = OpenAI(api_key=api_key)

arquivo_base = BASE_DIR / "perguntas_respostas.md"

if not arquivo_base.exists():
    raise FileNotFoundError(
        f"Documento não encontrado: {arquivo_base}"
    )

print(f"Arquivo que será enviado: {arquivo_base}")


# Repete até não sobrar nenhum arquivo anexado ao Vector Store.
while True:
    arquivos = client.vector_stores.files.list(
        vector_store_id=vector_store_id
    )

    if not arquivos.data:
        break

    for arquivo in arquivos.data:
        print(f"Removendo arquivo antigo: {arquivo.id}")

        client.vector_stores.files.delete(
            vector_store_id=vector_store_id,
            file_id=arquivo.id,
        )


with open(arquivo_base, "rb") as arquivo:
    novo_arquivo = client.files.create(
        file=arquivo,
        purpose="assistants",
    )

print(f"Arquivo enviado para OpenAI: {novo_arquivo.id}")

arquivo_vector_store = client.vector_stores.files.create(
    vector_store_id=vector_store_id,
    file_id=novo_arquivo.id,
)

while True:
    status = client.vector_stores.files.retrieve(
        vector_store_id=vector_store_id,
        file_id=arquivo_vector_store.id,
    )

    print(f"Status da indexação: {status.status}")

    if status.status == "completed":
        print("Base atualizada com sucesso.")
        break

    if status.status in ("failed", "cancelled"):
        raise RuntimeError(
            f"Indexação falhou: {status.status}"
        )

    time.sleep(1)