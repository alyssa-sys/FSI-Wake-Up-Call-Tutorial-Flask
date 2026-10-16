from extensions import db
from flask_login import UserMixin
from datetime import datetime

class Usuario(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    nomeUsuario = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False)
    senha = db.Column(db.String(255), nullable=False)
    nome = db.Column(db.String(100), nullable=False)
    tarefasCriadas = db.relationship('Tarefa', backref='criador', foreign_keys='Tarefa.criador_id', lazy=True)
    tarefasAtribuidas = db.relationship('Tarefa', backref='responsavel', foreign_keys='Tarefa.responsavel_id', lazy=True)
    cargo = db.Column(db.String(20), nullable=False, default='usuario') #admin ou usuario
    foto_perfil = db.Column(db.String(200), nullable=True, default='default.png')
    # # Tabela de associação para conexões entre usuários
    # conexoes = db.Table('conexoes',
    # db.Column('usuario_id', db.Integer, db.ForeignKey('usuario.id'), primary_key=True),
    # db.Column('amigo_id', db.Integer, db.ForeignKey('usuario.id'), primary_key=True))

class Tarefa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(150), nullable=False)
    descricao = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Pendente')
    prioridade = db.Column(db.String(20), nullable=False, default='A definir')
    prazo = db.Column(db.DateTime, nullable=True, index=True)
    criador_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    responsavel_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    equipe_id = db.Column(db.Integer, db.ForeignKey('equipe.id'), nullable=True)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categoria.id'), nullable=True)

class Equipe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    codigo_acesso = db.Column(db.String(12), unique=True, nullable=False)
    dono_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    dono = db.relationship('Usuario', foreign_keys=[dono_id])
    membros = db.relationship('MembroEquipe', backref='equipe', cascade='all, delete-orphan', lazy=True)
    tarefas = db.relationship('Tarefa', backref='equipe', lazy=True)

class MembroEquipe(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    equipe_id = db.Column(db.Integer, db.ForeignKey('equipe.id'), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    usuario = db.relationship('Usuario')
    __table_args__ = (db.UniqueConstraint('equipe_id', 'usuario_id'),)

class Categoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    tarefas = db.relationship('Tarefa', backref='categoria', lazy=True)
