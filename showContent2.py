from sqlalchemy import text
from textwrap import wrap
from dbConfig import db
from appCreate import create_app

app = create_app()

with app.app_context():
    session = db.session

    result = session.execute(text("""
        SELECT cliente_id, content
        FROM messages
        WHERE ts::date = CURRENT_DATE
        ORDER BY cliente_id DESC, ts ASC
    """))

    rows = result.fetchall()

    COL_ID = 10
    COL_CONTENT = 40

    for cliente_id, content in rows:
        linhas = wrap(content or "", COL_CONTENT) or [""]

        print(f"{str(cliente_id):<{COL_ID}} | {linhas[0]:<{COL_CONTENT}}")

        for linha in linhas[1:]:
            print(f"{'':<{COL_ID}} | {linha:<{COL_CONTENT}}")