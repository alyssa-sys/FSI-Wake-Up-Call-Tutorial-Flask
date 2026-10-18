from sqlalchemy import text
from app import app
from extensions import db

with app.app_context():
    db.create_all()  
    colunas = [linha[1] for linha in db.session.execute(text("PRAGMA table_info(tarefa)"))]
    if 'aceite' not in colunas:
        db.session.execute(text("ALTER TABLE tarefa ADD COLUMN aceite VARCHAR(20) NOT NULL DEFAULT 'aceita'"))
        db.session.commit()
        print("Coluna 'aceite' adicionada.")
    else:
        print("Coluna 'aceite' já existe.")