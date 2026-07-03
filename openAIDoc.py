import os
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    raise RuntimeError("OPENAI_API_KEY não foi encontrada no .env")

client = OpenAI(api_key=api_key)

# Use o MESMO ID que está no clientResponse.py
VECTOR_STORE_ID = "vs_6a4619a48bcc81919f1017b18e8d56a2"


def formatar_data(timestamp):
    return datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y %H:%M:%S")


after = None
quantidade_total = 0
quantidade_md = 0

print(f"\nVector Store consultado: {VECTOR_STORE_ID}\n")
print("===== ARQUIVOS ANEXADOS AO VECTOR STORE =====\n")

while True:
    pagina = client.vector_stores.files.list(
        vector_store_id=VECTOR_STORE_ID,
        limit=100,
        order="desc",
        after=after,
    )

    for arquivo_vs in pagina.data:
        quantidade_total += 1

        # O arquivo_vs.id é o file_id do arquivo enviado à OpenAI.
        arquivo_original = client.files.retrieve(arquivo_vs.id)

        nome = arquivo_original.filename
        eh_md = nome.lower().endswith(".md")

        if eh_md:
            quantidade_md += 1
            print("Arquivo .md encontrado")
            print(f"Nome: {nome}")
            print(f"File ID: {arquivo_vs.id}")
            print(f"Status: {arquivo_vs.status}")
            print(f"Anexado em: {formatar_data(arquivo_vs.created_at)}")
            print(f"Uso no Vector Store: {arquivo_vs.usage_bytes} bytes")

            if arquivo_vs.last_error:
                print(f"Erro: {arquivo_vs.last_error}")

            print("-" * 60)

    if not pagina.has_more:
        break

    after = pagina.last_id

print(f"\nTotal de arquivos anexados: {quantidade_total}")
print(f"Total de arquivos .md: {quantidade_md}")

if quantidade_md == 0:
    print("\nNenhum arquivo .md está anexado a esse Vector Store.")
elif quantidade_md == 1:
    print("\nCorreto: existe apenas um arquivo .md anexado.")
else:
    print(
        "\nATENÇÃO: existem vários arquivos .md anexados. "
        "Isso pode fazer o File Search recuperar regras antigas."
    )