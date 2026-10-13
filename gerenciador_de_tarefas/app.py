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

#editar tarefa
@app.route('/editar_tarefa/<int:tarefa_id>', methods=['GET', 'POST'])
@login_required
def editar_tarefa(tarefa_id):
    tarefa = db.get_or_404(Tarefa, tarefa_id)

    if not pode_mudar_status(tarefa):
        flash('Você não tem permissão para editar esta tarefa.', 'danger')
        return voltar_para_lista()
    
    if request.method == 'POST':
        status = request.form['status']
        if status not in STATUS_VALIDOS:
            flash('Status inválido.', 'danger')
            return redirect(url_for('editar_tarefa', tarefa_id=tarefa_id))

        tarefa.status = status

        # só criador e admin alteram título e descrição
        if pode_editar(tarefa):
            prioridade = request.form.get('prioridade', tarefa.prioridade or 'A definir')
            if prioridade not in PRIORIDADES_VALIDAS:
                flash('Prioridade inválida.', 'danger')
                return redirect(url_for('editar_tarefa', tarefa_id=tarefa_id))
            try:
                prazo = validar_prazo(request.form.get('prazo'))
            except ValueError as e:
                flash(str(e), 'danger')
                return redirect(url_for('editar_tarefa', tarefa_id=tarefa_id))
            tarefa.titulo = request.form['titulo'].strip()
            tarefa.descricao = request.form['descricao'].strip()
            tarefa.prioridade = prioridade
            tarefa.prazo = prazo

        db.session.commit()
        flash('Tarefa atualizada com sucesso!', 'success')
        return voltar_para_lista()
    return render_template('editar_tarefa.html', tarefa=tarefa, agora=datetime.now())

#alterar apenas o status (usado pelo painel admin)
@app.route('/alterar_status/<int:tarefa_id>', methods=['POST'])
@login_required
def alterar_status(tarefa_id):
    tarefa = db.get_or_404(Tarefa, tarefa_id)
    if not pode_mudar_status(tarefa):
        flash('Você não tem permissão para alterar o status desta tarefa.', 'danger')
        return voltar_para_lista()

    status = request.form.get('status')
    if status not in STATUS_VALIDOS:
        flash('Status inválido.', 'danger')
        return voltar_para_lista()

    tarefa.status = status
    db.session.commit()
    flash('Status atualizado!', 'success')
    return voltar_para_lista()

#excluir tarefa
@app.route('/excluir_tarefa/<int:tarefa_id>', methods=['POST'])
@login_required
def excluir_tarefa(tarefa_id):
    tarefa = db.get_or_404(Tarefa, tarefa_id)
    if not pode_excluir(tarefa):
        flash('Só o criador da tarefa (ou um admin) pode excluí-la. Use o status "Cancelada" se não quiser fazê-la.', 'danger')
        return voltar_para_lista()

    db.session.delete(tarefa)
    db.session.commit()

    flash('Tarefa excluída com sucesso!', 'success')
    return voltar_para_lista()