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


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))


def validar_prazo(valor):
    valor = (valor or '').strip()
    if not valor:
        return None
    try:
        prazo = datetime.strptime(valor, '%Y-%m-%dT%H:%M')
    except ValueError:
        raise ValueError('Data e hora do prazo inválidas')
    if prazo <= datetime.now():
        raise ValueError('O prazo deve ser uma data e hora futura')
    return prazo


def tarefa_atrasada(tarefa):
    if tarefa.prazo is None:
        return False
    if tarefa.status in ['Concluída', 'Cancelada']:
        return False
    return tarefa.prazo < datetime.now()


# ---------------------------------------------------------------
# Permissões das tarefas
#   Criador:     vê, edita tudo, muda o status e exclui.
#   Responsável: vê e muda o status. Não exclui.
#   Admin:       faz tudo em qualquer tarefa, inclusive pelo painel.
# ---------------------------------------------------------------
def eh_admin():
    return getattr(current_user, 'cargo', None) == 'admin'

def pode_editar(tarefa):
    return eh_admin() or current_user.id == tarefa.criador_id

def pode_excluir(tarefa):
    return eh_admin() or current_user.id == tarefa.criador_id

def pode_mudar_status(tarefa):
    return pode_editar(tarefa) or current_user.id == tarefa.responsavel_id

def voltar_para_lista():
    return redirect(url_for('admin_dashboard') if eh_admin() else url_for('quadro'))

# deixa as funções disponíveis em todos os templates (inclusive dentro de macros)
app.jinja_env.globals.update(
    pode_editar=pode_editar,
    pode_excluir=pode_excluir,
    pode_mudar_status=pode_mudar_status,
    eh_admin=eh_admin,
    tarefa_atrasada=tarefa_atrasada,
)


@app.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('quadro'))
    return redirect(url_for('login'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        nomeUsuario = request.form['nomeUsuario'].strip()
        if not nomeUsuario:
            flash('O nome de usuário é obrigatório.', 'danger')
            return redirect(url_for('registro'))
        nome = request.form.get('nome', '').strip() or nomeUsuario
        senha = generate_password_hash(request.form['senha'])

        usuario = Usuario.query.filter((Usuario.email == email) | (Usuario.nomeUsuario == nomeUsuario)).first()
        if usuario:
            flash('Já existe um usuário com esse email ou nome de usuário.', 'danger')
            return redirect(url_for('registro'))

        novo_usuario = Usuario(nomeUsuario=nomeUsuario, nome=nome, email=email, senha=senha) # type: ignore
        db.session.add(novo_usuario)
        db.session.commit()

        flash('Usuário registrado com sucesso!', 'success')
        return redirect(url_for('login'))

    return render_template('registro.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identificador = request.form['identificador'].strip()
        senha = request.form['senha']

        usuario = Usuario.query.filter(
            (Usuario.email == identificador.lower()) | (Usuario.nomeUsuario == identificador)
        ).first()

        if usuario and check_password_hash(usuario.senha, senha):
            login_user(usuario)
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('admin_dashboard') if usuario.cargo == 'admin' else url_for('quadro'))
        else:
            flash('Usuário/e-mail ou senha incorretos.', 'danger')

    return render_template('login.html')
#admin
@app.route('/admin')
@login_required
def admin_dashboard():
    if not eh_admin():
        flash("Acesso negado!", 'danger')
        return redirect(url_for('quadro'))

    tarefas = Tarefa.query.all()
    return render_template('quadro_admin.html', tarefas = tarefas)

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

#rota do quadro (Dashboard)
@app.route('/quadro')
@login_required
def quadro():
    recebidas = Tarefa.query.filter(
        Tarefa.responsavel_id == current_user.id,
        Tarefa.criador_id != current_user.id
    ).all()
    para_mim = Tarefa.query.filter(
        Tarefa.responsavel_id == current_user.id,
        Tarefa.criador_id == current_user.id
    ).all()
    delegadas = Tarefa.query.filter(
        Tarefa.criador_id == current_user.id,
        Tarefa.responsavel_id != current_user.id
    ).all()
    return render_template('quadro.html',
                           atribuidas_a_mim=recebidas + para_mim,
                           delegadas=delegadas)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)