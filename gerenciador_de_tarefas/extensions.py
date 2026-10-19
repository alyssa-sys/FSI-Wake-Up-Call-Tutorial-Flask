import os
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# A Vercel roda em UTC. Para os prazos baterem com o seu relógio, usamos o fuso abaixo
# (troque pela variável de ambiente FUSO_HORARIO, ex.: America/Manaus).
try:
    from zoneinfo import ZoneInfo
    _FUSO = ZoneInfo(os.environ.get('FUSO_HORARIO', 'America/Sao_Paulo'))
except Exception:  # sem base de fusos instalada: usa o relógio da máquina
    _FUSO = None


def agora_local():
    """datetime.now() no fuso configurado, sem tzinfo (igual ao que o app já usava)."""
    if _FUSO is None:
        return datetime.now()
    return datetime.now(_FUSO).replace(tzinfo=None)