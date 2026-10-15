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

class Tarefa(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(150), nullable=False)
    descricao = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Pendente')
    prioridade = db.Column(db.String(20), nullable=False, default='A definir')
    prazo = db.Column(db.DateTime, nullable=True, index=True)
    criador_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)
    responsavel_id = db.Column(db.Integer, db.ForeignKey('usuario.id'), nullable=False)