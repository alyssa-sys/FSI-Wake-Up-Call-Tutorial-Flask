# ! Este script adiciona um usuário admin padrão ao banco de dados.

import sqlite3
from werkzeug.security import generate_password_hash

senha = generate_password_hash("admin", method="scrypt")

connection = sqlite3.connect('instance/gerenciador_de_tarefas.db')
query = connection.cursor()

try:
    query.execute("""
        INSERT INTO Usuario (nomeUsuario, nome, email, senha, cargo)
        VALUES (?, ?, ?, ?, ?)
    """, ("admin", "Administrador", "admin@example.com", senha, "admin")) 
    
    connection.commit()
    
    print("Usuário admin criado com sucesso.")
    
except sqlite3.IntegrityError:
    print("Erro: O usuário já existe")

except sqlite3.OperationalError:
    print("Erro: verifique se a tabela e atributos estão corretos.")

connection.close()