"""
Cria as tabelas no banco e o usuário admin (rode UMA vez, no seu computador).

Uso (dentro da pasta gerenciador_de_tarefas):
  Windows (PowerShell):
      $env:DATABASE_URL = "postgresql://...string do Neon..."
      $env:ADMIN_SENHA = "uma-senha-forte"
      python criar_banco.py
  Linux/Mac:
      DATABASE_URL="postgresql://..." ADMIN_SENHA="uma-senha-forte" python criar_banco.py

Sem DATABASE_URL ele mexe no SQLite local.
"""
import os

from werkzeug.security import generate_password_hash

from app import app, garantir_schema
from extensions import db
from models import Usuario

senha = os.environ.get('ADMIN_SENHA')
if not senha:
    raise SystemExit('Defina a variável ADMIN_SENHA antes de rodar (a senha do usuário admin).')

with app.app_context():
    garantir_schema()
    print('Tabelas ok.')

    if Usuario.query.filter_by(nomeUsuario='admin').first():
        print('O usuário admin já existe. Nada a fazer.')
    else:
        db.session.add(Usuario(  # type: ignore
            nomeUsuario='admin', nome='Administrador', email='admin@example.com',
            senha=generate_password_hash(senha), cargo='admin',
        ))
        db.session.commit()
        print('Usuário admin criado (login: admin).')