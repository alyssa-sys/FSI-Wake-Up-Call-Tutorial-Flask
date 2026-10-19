from sqlalchemy import text
from app import app
from extensions import db

# Etapa "admin da equipe": adiciona a coluna membro_equipe.admin no banco que já existe.
# Rode uma vez (python migrar_equipe_admin.py) em cada computador que tenha um banco antigo.
with app.app_context():
    db.create_all()
    colunas = [linha[1] for linha in db.session.execute(text("PRAGMA table_info(membro_equipe)"))]
    if 'admin' not in colunas:
        db.session.execute(text("ALTER TABLE membro_equipe ADD COLUMN admin BOOLEAN NOT NULL DEFAULT 0"))
        db.session.commit()
        print("Coluna 'admin' adicionada em membro_equipe.")
    else:
        print("Coluna 'admin' já existe.")