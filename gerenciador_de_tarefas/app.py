from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from models import Usuario, Tarefa

app = Flask(__name__)
app.config['SECRET_KEY'] = 'chaveMuitoMuitoSecreta'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///gerenciador_de_tarefas.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # type: ignore

# Rota quadro/dashboard
@app.route('/quadro')
@login_required
def quadro():
    tarefas = Task.query.filter_by(created_by =current_user.id).all()
    tarefas_compartilhadas = Task.query.filter_by(shared_with = current_user.id).all()
    return render_template('quadro.html', tarefas = tarefas, tarefas_compartilhadas = tarefas_compartilhadas)
# sujeito a mudanças, ainda a definir variáveis e funções

# Rota quadro(admin)
@app.route('/admin')
@login_required
def quadro_admin():
    if current_user.role != 'admin':
        flash("Acesso não autorizado", 'danger')
        return redirect(url_for('quadro'))

    tarefas = Task.query.all()
    return render_template('quado_admin.html', tarefas = tarefas)
# sujeito a mudanças, feitos sem 'from flask import Flask'

#adicionar tarefa
STATUS_VALIDOS = ['Pendente', 'Em andamento', 'Concluída', 'Cancelada']
PRIORIDADES_VALIDAS = ['Alta', 'Média', 'Baixa', 'A definir']

@app.route('/adicionar_tarefa', methods=['GET', 'POST'])
@login_required
def adicionar_tarefa():
    if request.method == 'POST':
        titulo = request.form['titulo'].strip()
        descricao = request.form['descricao'].strip()
        status = 'Pendente'

        prioridade = request.form.get('prioridade', 'A definir')

        if prioridade not in PRIORIDADES_VALIDAS:
            flash('Prioridade inválida.', 'danger')
            return redirect(url_for('adicionar_tarefa'))

        try:
            prazo = validar_prazo(request.form.get('prazo'))
        except ValueError as e:
            flash(str(e), 'danger')
            return redirect(url_for('adicionar_tarefa'))

        try:
            responsavel_id = int(request.form.get('responsavel_id') or current_user.id)
        except ValueError:
            flash('ID do responsável inválido.', 'danger')
            return redirect(url_for('adicionar_tarefa'))
        
        if not db.session.get(Usuario, responsavel_id):
            flash('Usuário responsável não encontrado.', 'danger')
            return redirect(url_for('adicionar_tarefa'))

        nova_tarefa = Tarefa(titulo=titulo, descricao=descricao, status=status, prioridade=prioridade, prazo=prazo, criador_id=current_user.id, responsavel_id=responsavel_id) # type: ignore

        db.session.add(nova_tarefa)
        db.session.commit()

        flash('Tarefa adicionada com sucesso!', 'success')
        return voltar_para_lista()

    usuarios = Usuario.query.filter(Usuario.id != current_user.id).all()
    return render_template('adicionar_tarefa.html', usuarios=usuarios, agora=datetime.now())
