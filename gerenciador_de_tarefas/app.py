

















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



















































#admin
@app.route('/admin')
@login_required
def admin_dashboard():
    if not eh_admin():
        flash("Acesso negado!", 'danger')
        return redirect(url_for('quadro'))

    tarefas = Tarefa.query.all()
    return render_template('quadro_admin.html', tarefas = tarefas)























































































































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
