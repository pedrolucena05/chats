from main import app, db

def reset_database():
    with app.app_context():
        print("🗑️ Apagando todas as tabelas...")
        db.drop_all()

        print("🆕 Criando todas as tabelas...")
        db.create_all()

        print("✅ Banco recriado com sucesso.")

if __name__ == "__main__":
    reset_database()
