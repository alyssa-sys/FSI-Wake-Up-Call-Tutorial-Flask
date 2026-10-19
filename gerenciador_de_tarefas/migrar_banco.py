"""
Deixa o banco (SQLite) em dia com o models.py: cria tabelas que faltam e
acrescenta colunas que faltam em tabelas que ja existem.

O db.create_all() do Flask-SQLAlchemy NAO adiciona colunas em tabelas existentes;
por isso aparecem erros como "no such column: usuario.ordenacao_quadro".

Uso (dentro da pasta gerenciador_de_tarefas, com o venv ativo):
    python migrar_banco.py             -> so MOSTRA o que seria feito
    python migrar_banco.py --aplicar   -> faz backup do banco e aplica

Nao apaga nem altera dados existentes.
"""
import shutil
import sys
from datetime import datetime

from sqlalchemy import inspect, text

from app import app
from extensions import db
import models  # noqa: F401  (garante que todos os modelos estao registrados)

APLICAR = '--aplicar' in sys.argv


def literal_sql(valor):
    if isinstance(valor, bool):
        return '1' if valor else '0'
    if isinstance(valor, (int, float)):
        return str(valor)
    return "'" + str(valor).replace("'", "''") + "'"


def valor_padrao(coluna):
    """DEFAULT SQL da coluna (server_default ou default simples do Python), ou None."""
    if coluna.server_default is not None:
        arg = coluna.server_default.arg
        return literal_sql(getattr(arg, 'text', arg))
    if coluna.default is not None and coluna.default.is_scalar:
        return literal_sql(coluna.default.arg)
    return None


with app.app_context():
    inspetor = inspect(db.engine)
    tabelas_existentes = set(inspetor.get_table_names())

    novas_tabelas = [t.name for t in db.metadata.sorted_tables if t.name not in tabelas_existentes]
    comandos, avisos = [], []

    for tabela in db.metadata.sorted_tables:
        if tabela.name not in tabelas_existentes:
            continue
        existentes = {c['name'] for c in inspetor.get_columns(tabela.name)}
        for coluna in tabela.columns:
            if coluna.name in existentes:
                continue
            tipo = coluna.type.compile(db.engine.dialect)
            padrao = valor_padrao(coluna)
            ddl = f'ALTER TABLE "{tabela.name}" ADD COLUMN "{coluna.name}" {tipo}'
            if padrao is not None:
                ddl += f' DEFAULT {padrao}'
            if not coluna.nullable:
                if padrao is None:
                    avisos.append(f'{tabela.name}.{coluna.name}: obrigatoria e sem valor padrao; '
                                  'nao da para adicionar automaticamente (me avise).')
                    continue
                ddl += ' NOT NULL'
            comandos.append((f'{tabela.name}.{coluna.name}', ddl))

    print(f'Banco: {db.engine.url.database}\n')
    print('Tabelas que faltam :', ', '.join(novas_tabelas) or 'nenhuma')
    print('Colunas que faltam :', ', '.join(n for n, _ in comandos) or 'nenhuma')
    for a in avisos:
        print('ATENCAO:', a)

    if not novas_tabelas and not comandos:
        print('\nBanco ja esta em dia com o models.py. Nada a fazer.')
        sys.exit(0)

    if not APLICAR:
        print('\n(Nada foi alterado. Rode com --aplicar para executar.)')
        sys.exit(0)

    arquivo = db.engine.url.database
    if arquivo and arquivo != ':memory:':
        backup = f'{arquivo}.backup-{datetime.now():%Y%m%d-%H%M%S}'
        shutil.copy2(arquivo, backup)
        print(f'\nBackup criado: {backup}')

    db.create_all()  # cria so as tabelas que faltam
    for nome, ddl in comandos:
        db.session.execute(text(ddl))
        print('Coluna adicionada:', nome)
    db.session.commit()
    print('\nPronto. Reinicie o servidor.')
