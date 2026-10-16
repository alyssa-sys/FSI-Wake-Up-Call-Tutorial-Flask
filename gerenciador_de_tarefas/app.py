import secrets
from models import Usuario, Tarefa, Equipe, MembroEquipe
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


def eh_admin():
    return getattr(current_user, 'cargo', None) == 'admin'

def pode_editar(tarefa):
    return eh_admin() or current_user.id == tarefa.criador_id

def pode_excluir(tarefa):
    return eh_admin() or current_user.id == tarefa.criador_id

def pode_mudar_status(tarefa):
    return pode_editar(tarefa) or current_user.id == tarefa.responsavel_id

def voltar_para_lista(equipe_id=None):
    if equipe_id:
        return redirect(url_for('ver_equipe', equipe_id=equipe_id))
    return redirect(url_for('admin_dashboard') if eh_admin() else url_for('quadro'))

app.jinja_env.globals.update(
    pode_editar=pode_editar,
    pode_excluir=pode_excluir,
    pode_mudar_status=pode_mudar_status,
    eh_admin=eh_admin,
    tarefa_atrasada=tarefa_atrasada,
)

def eh_membro(equipe):
    return MembroEquipe.query.filter_by(equipe_id=equipe.id, usuario_id=current_user.id).first() is not None

def eh_dono(equipe):
    return current_user.id == equipe.dono_id

def gerar_codigo():
    while True:
        codigo = secrets.token_hex(4).upper()
        if not Equipe.query.filter_by(codigo_acesso=codigo).first():
            return codigo

def contar_status(tarefas):
    return [sum(1 for t in tarefas if t.status == s) for s in STATUS_VALIDOS]

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
        nome = request.form.get('nome') or nomeUsuario
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
        email = request.form['email'].strip().lower()
        senha = request.form['senha']

        usuario = Usuario.query.filter_by(email=email).first()
        if usuario and check_password_hash(usuario.senha, senha):
            login_user(usuario)
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('admin_dashboard') if usuario.cargo == 'admin' else url_for('quadro'))
        else:
            flash('Email ou senha incorretos.', 'danger')

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
        return voltar_para_lista(tarefa.equipe_id)

    if request.method == 'POST':
        status = request.form['status']
        if status not in STATUS_VALIDOS:
            flash('Status inválido.', 'danger')
            return redirect(url_for('editar_tarefa', tarefa_id=tarefa_id))

        tarefa.status = status

        # só criador e admin alteram título, descrição, prioridade e prazo
        if pode_editar(tarefa):
            prioridade = request.form.get('prioridade', tarefa.prioridade or 'A definir')
            if prioridade not in PRIORIDADES_VALIDAS:
                flash('Prioridade inválida.', 'danger')
                return redirect(url_for('editar_tarefa', tarefa_id=tarefa_id))
            try:
                prazo = validar_prazo(request.form.get('prazo'))
            except ValueError as e:
                prazo_enviado = request.form.get('prazo', '').strip()
                prazo_atual = tarefa.prazo.strftime('%Y-%m-%dT%H:%M') if tarefa.prazo else None
                if prazo_atual and prazo_enviado == prazo_atual:
                    prazo = tarefa.prazo  # não mudou, mantém mesmo vencido
                else:
                    flash(str(e), 'danger')
                    return redirect(url_for('editar_tarefa', tarefa_id=tarefa_id))

            tarefa.titulo = request.form['titulo'].strip()
            tarefa.descricao = request.form['descricao'].strip()
            tarefa.prioridade = prioridade
            tarefa.prazo = prazo

        db.session.commit()
        flash('Tarefa atualizada com sucesso!', 'success')
        return voltar_para_lista(tarefa.equipe_id)
    return render_template('editar_tarefa.html', tarefa=tarefa, agora=datetime.now())

#alterar apenas o status (usado pelo painel admin)
@app.route('/alterar_status/<int:tarefa_id>', methods=['POST'])
@login_required
def alterar_status(tarefa_id):
    tarefa = db.get_or_404(Tarefa, tarefa_id)
    if not pode_mudar_status(tarefa):
        flash('Você não tem permissão para alterar o status desta tarefa.', 'danger')
        return voltar_para_lista(tarefa.equipe_id)

    status = request.form.get('status')
    if status not in STATUS_VALIDOS:
        flash('Status inválido.', 'danger')
        return voltar_para_lista(tarefa.equipe_id)

    tarefa.status = status
    db.session.commit()
    flash('Status atualizado!', 'success')
    return voltar_para_lista(tarefa.equipe_id)

#excluir tarefa
@app.route('/excluir_tarefa/<int:tarefa_id>', methods=['POST'])
@login_required
def excluir_tarefa(tarefa_id):
    tarefa = db.get_or_404(Tarefa, tarefa_id)
    equipe_id = tarefa.equipe_id  # guarda antes de apagar, para voltar à tela certa

    if not pode_excluir(tarefa):
        flash('Só o criador da tarefa (ou um admin) pode excluí-la. Use o status "Cancelada" se não quiser fazê-la.', 'danger')
        return voltar_para_lista(equipe_id)

    db.session.delete(tarefa)
    db.session.commit()

    flash('Tarefa excluída com sucesso!', 'success')
    return voltar_para_lista(equipe_id)

#rota do quadro (Dashboard)
@app.route('/quadro')
@login_required
def quadro():
    recebidas = Tarefa.query.filter(
        Tarefa.responsavel_id == current_user.id,
        Tarefa.criador_id != current_user.id,
        Tarefa.equipe_id.is_(None)
    ).all()
    para_mim = Tarefa.query.filter(
        Tarefa.responsavel_id == current_user.id,
        Tarefa.criador_id == current_user.id,
        Tarefa.equipe_id.is_(None)
    ).all()
    delegadas = Tarefa.query.filter(
        Tarefa.criador_id == current_user.id,
        Tarefa.responsavel_id != current_user.id,
        Tarefa.equipe_id.is_(None)
    ).all()
    atribuidas = recebidas + para_mim
    return render_template('quadro.html',
                           atribuidas_a_mim=atribuidas,
                           delegadas=delegadas,
                           grafico=contar_status(atribuidas))

#rota das equipes
@app.route('/equipes')
@login_required
def equipes():
    minhas = Equipe.query.filter_by(dono_id=current_user.id).all()
    participo = (Equipe.query.join(MembroEquipe, MembroEquipe.equipe_id == Equipe.id)).filter(MembroEquipe.usuario_id == current_user.id, Equipe.dono_id != current_user.id).all()
    return render_template('equipes.html', minhas=minhas, participo=participo)

@app.route('/equipes/criar', methods=['POST'])
@login_required
def criar_equipe():
    nome = request.form.get('nome', '').strip()
    if not nome:
        flash('Dê um nome para a equipe.', 'danger')
        return redirect(url_for('equipes'))
    equipe = Equipe(nome=nome[:100], dono_id=current_user.id, codigo_acesso=gerar_codigo())
    db.session.add(equipe)
    db.session.flush()
    db.session.add(MembroEquipe(equipe_id=equipe.id, usuario_id=current_user.id))
    db.session.commit()
    flash('Equipe criada!', 'success')
    return redirect(url_for('ver_equipe', equipe_id=equipe.id))

@app.route('/equipes/entrar', methods=['POST'])
@login_required
def entrar_equipe():
    codigo = request.form.get('codigo', '').strip().upper()
    equipe = Equipe.query.filter_by(codigo_acesso=codigo).first()
    if not equipe:
        flash('Código de acesso inválido.', 'danger')
        return redirect(url_for('equipes'))
    if eh_membro(equipe):
        flash('Você já é membro desta equipe.', 'info')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))
    db.session.add(MembroEquipe(equipe_id=equipe.id, usuario_id=current_user.id))
    db.session.commit()
    flash(f'Você entrou na equipe "{equipe.nome}".', 'success')
    return redirect(url_for('ver_equipe', equipe_id=equipe.id))

@app.route('/equipes/<int:equipe_id>')
@login_required
def ver_equipe(equipe_id):
    equipe = db.get_or_404(Equipe, equipe_id)
    if not eh_membro(equipe):
        flash('Você não faz parte dessa equipe.', 'danger')
        return redirect(url_for('equipes'))
    tarefas = Tarefa.query.filter_by(equipe_id=equipe.id).all()
    return render_template('equipe.html', equipe=equipe, tarefas=tarefas,
                           membros=equipe.membros, dono=eh_dono(equipe),
                           grafico=contar_status(tarefas))

@app.route('/equipes/<int:equipe_id>/adicionar_tarefa', methods=['GET', 'POST'])
@login_required
def adicionar_tarefa_equipe(equipe_id):
    equipe = db.get_or_404(Equipe, equipe_id)
    if not eh_dono(equipe):
        flash('Só o criador da equipe pode atribuir tarefas.', 'danger')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))
    membros = [m.usuario for m in equipe.membros]

    if request.method == 'POST':
        titulo = request.form['titulo'].strip()
        descricao = request.form['descricao'].strip()
        prioridade = request.form.get('prioridade', 'A definir')
        if prioridade not in PRIORIDADES_VALIDAS:
            flash('Prioridade inválida.', 'danger')
            return redirect(url_for('adicionar_tarefa_equipe', equipe_id=equipe.id))
        try:
            prazo = validar_prazo(request.form.get('prazo'))
        except ValueError as e:
            flash(str(e), 'danger')
            return redirect(url_for('adicionar_tarefa_equipe', equipe_id=equipe.id))
        try:
            responsavel_id = int(request.form.get('responsavel_id') or 0)
        except ValueError:
            responsavel_id = 0
        if responsavel_id not in {u.id for u in membros}:
            flash('Escolha um membro da equipe como responsável.', 'danger')
            return redirect(url_for('adicionar_tarefa_equipe', equipe_id=equipe.id))

        nova_tarefa = Tarefa(titulo=titulo, descricao=descricao, status='Pendente', prioridade=prioridade, prazo=prazo, criador_id=current_user.id, responsavel_id=responsavel_id, equipe_id=equipe.id) # type: ignore
        db.session.add(nova_tarefa)
        db.session.commit()
        flash('Tarefa atribuida!', 'success')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))

    return render_template('adicionar_tarefa_equipe.html', equipe=equipe, membros=membros, agora=datetime.now())

@app.route('/equipes/<int:equipe_id>/novo_codigo', methods=['POST'])
@login_required
def novo_codigo_equipe(equipe_id):
    equipe = db.get_or_404(Equipe, equipe_id)
    if not eh_dono(equipe):
        flash('Só o criador da equipe pode gerar um novo código.', 'danger')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))
    equipe.codigo_acesso = gerar_codigo()
    db.session.commit()
    flash('Novo código gerado. O anterior não vale mais.', 'success')
    return redirect(url_for('ver_equipe', equipe_id=equipe.id))

@app.route('/equipes/<int:equipe_id>/remover/<int:usuario_id>', methods=['POST'])
@login_required
def remover_membro(equipe_id, usuario_id):
    equipe = db.get_or_404(Equipe, equipe_id)
    sair = usuario_id == current_user.id
    if sair and eh_dono(equipe):
        flash('O criador não pode sair da própria equipe. Exclua a equipe se quiser encerrá-la.', 'danger')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))
    if not sair and not eh_dono(equipe):
        flash('Só o criador pode remover membros.', 'danger')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))
    membro = MembroEquipe.query.filter_by(equipe_id=equipe.id, usuario_id=usuario_id).first_or_404()

    # tarefas do membro que saiu: as não concluídas viram "Cancelada" e passam para o criador
    tarefas_do_membro = Tarefa.query.filter_by(equipe_id=equipe.id, responsavel_id=usuario_id).all()
    for t in tarefas_do_membro:
        if t.status != 'Concluída':
            t.status = 'Cancelada'
        t.responsavel_id = equipe.dono_id

    db.session.delete(membro)
    db.session.commit()
    flash('Você saiu da equipe.' if sair else 'Membro removido.', 'success')
    return redirect(url_for('equipes') if sair else url_for('ver_equipe', equipe_id=equipe.id))

@app.route('/equipes/<int:equipe_id>/excluir', methods=['POST'])
@login_required
def excluir_equipe(equipe_id):
    equipe = db.get_or_404(Equipe, equipe_id)
    if not eh_dono(equipe):
        flash('Só o criador pode excluir a equipe.', 'danger')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))

    Tarefa.query.filter_by(equipe_id=equipe.id).delete()
    db.session.delete(equipe)  # os membros são apagados junto (cascade)
    db.session.commit()
    flash('Equipe excluída.', 'success')
    return redirect(url_for('equipes'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)