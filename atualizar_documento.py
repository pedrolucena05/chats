from openai import OpenAI
import os
import time

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

VECTOR_STORE_ID = "vs_6a4619a48bcc81919f1017b18e8d56a2"
ARQUIVO_ATUALIZADO = "perguntas_respostas.md"


def remover_arquivos_antigos():
    arquivos = client.vector_stores.files.list(
        vector_store_id=VECTOR_STORE_ID
    )

    for arquivo in arquivos.data:
        print(f"Removendo do Vector Store: {arquivo.id}")

        client.vector_stores.files.delete(
            vector_store_id=VECTOR_STORE_ID,
            file_id=arquivo.id
        )


def enviar_novo_arquivo():
    with open(ARQUIVO_ATUALIZADO, "rb") as arquivo:
        arquivo_openai = client.files.create(
            file=arquivo,
            purpose="assistants"
        )

    print(f"Novo arquivo enviado: {arquivo_openai.id}")

    client.vector_stores.files.create(
        vector_store_id=VECTOR_STORE_ID,
        file_id=arquivo_openai.id
    )

    return arquivo_openai.id


def aguardar_indexacao(file_id):
    while True:
        arquivos = client.vector_stores.files.list(
            vector_store_id=VECTOR_STORE_ID
        )

        arquivo_atual = next(
            (item for item in arquivos.data if item.id == file_id),
            None
        )

        if not arquivo_atual:
            print("Arquivo ainda não apareceu no Vector Store.")
            time.sleep(2)
            continue

        print(f"Status da indexação: {arquivo_atual.status}")

        if arquivo_atual.status == "completed":
            print("Base atualizada e pronta para uso.")
            break

        if arquivo_atual.status in ["failed", "cancelled"]:
            raise RuntimeError(
                f"Erro ao indexar arquivo: {arquivo_atual.last_error}"
            )

        time.sleep(2)


remover_arquivos_antigos()
novo_file_id = enviar_novo_arquivo()
aguardar_indexacao(novo_file_id)