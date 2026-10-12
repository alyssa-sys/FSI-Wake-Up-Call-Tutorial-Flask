CLASSES_STATUS = {
    'Pendente': 'status-pendente',
    'Em andamento': 'status-andamento',
    'Concluída': 'status-concluida',
    'Cancelada': 'status-cancelada'
}
STATUS_VALIDOS = list(CLASSES_STATUS)
STATUS_ENCERRADOS = ['Concluída', 'Cancelada']
PRIORIDADES_VALIDAS = ['Alta', 'Média', 'Baixa', 'A definir']

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))


def validar_prazo(valor, atual=None):
    valor = (valor or '').strip()
    if not valor:
        return None
    try:
        prazo = datetime.strptime(valor, '%Y-%m-%dT%H:%M')
    except ValueError:
        raise ValueError('Data e hora do prazo inválidas')
    if atual is not None and prazo == atual.replace(second=0, microsecond=0):
        return atual
    if prazo <= datetime.now():
        raise ValueError('O prazo deve ser uma data e hora futura')
    return prazo


def tarefa_atrasada(tarefa):
    if tarefa.prazo is None:
        return False
    if tarefa.status in STATUS_ENCERRADOS:
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
    CLASSES_STATUS=CLASSES_STATUS,
    STATUS_VALIDOS=STATUS_VALIDOS,
    PRIORIDADES_VALIDAS=PRIORIDADES_VALIDAS
)

@app.route('/')
def home():
    if current_user.is_authenticated:
        return voltar_para_lista()
    return redirect(url_for('login'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        nomeUsuario = request.form['nomeUsuario'].strip()
        if not nomeUsuario or len(nomeUsuario) > 50 or '@' in nomeUsuario:
            flash('Nome de usuário inválido. Use até 50 caracteres, exceto "@".', 'danger')
            return redirect(url_for('registro'))
        
        nome = request.form.get('nome', '').strip() or nomeUsuario

        if len(nome) > 100 or len(email) > 254:
            flash('Nome ou e-mail muito longos.', 'danger')
            return redirect(url_for('registro'))
        
        senha_digitada = request.form['senha']

        if len(senha_digitada) < 4:
            flash('A senha deve ter pelo menos 4 caracteres.', 'danger')
            return redirect(url_for('registro'))
        
        senha = generate_password_hash(senha_digitada  )

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

#admin (sujeito a mudanças)

@app.route('/admin')
@login_required
def admin_dashboard():
    if not eh_admin():
        flash("Acesso negado!", 'danger')
        return redirect(url_for('quadro'))

    tarefas = Tarefa.query.all()
    return render_template('quadro_admin.html', tarefas = tarefas)

# Rota quadro/dashboard
@app.route('/quadro')
@login_required
def quadro():
    tarefas = Task.query.filter_by(created_by =current_user.id).all()
    tarefas_compartilhadas = Task.query.filter_by(shared_with = current_user.id).all()
    return render_template('quadro.html', tarefas = tarefas, tarefas_compartilhadas = tarefas_compartilhadas)
# sujeito a mudanças, ainda a definir variáveis e funções