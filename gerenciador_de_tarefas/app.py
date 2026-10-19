import secrets
import smtplib
from email.message import EmailMessage
from markupsafe import escape
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from models import Usuario, Tarefa, Equipe, MembroEquipe, Categoria, Contato, ConviteEquipe, CategoriaCompartilhada, Subtarefa
from sqlalchemy import or_, and_, text, inspect
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, Response, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from extensions import db, agora_local
from werkzeug.security import generate_password_hash, check_password_hash
import os
from werkzeug.utils import secure_filename
from urllib.parse import quote

# Fotos de perfil: ficam no banco de dados (a Vercel não permite gravar arquivos)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
TAMANHO_MAX_FOTO = 1024 * 1024  # 1 MB

def arquivo_permitido(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# static_folder aponta para public/static: a Vercel serve a pasta public/ pela CDN
# e, rodando local, o Flask serve a mesma pasta.
app = Flask(__name__, static_folder='public/static')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'chaveMuitoMuitoSecreta')

# Na Vercel: DATABASE_URL = string de conexão do Neon (Postgres).
# Sem DATABASE_URL (rodando no seu PC) continua usando o SQLite de sempre.
_db_url = os.environ.get('DATABASE_URL', '').strip()
# Força o driver psycopg2 (o SQLAlchemy novo usaria o 'psycopg', que não está instalado)
for _prefixo in ('postgres://', 'postgresql://'):
    if _db_url.startswith(_prefixo):
        _db_url = 'postgresql+psycopg2://' + _db_url[len(_prefixo):]
        break
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url or 'sqlite:///gerenciador_de_tarefas.db'
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024  # limite de upload da Vercel: 4,5 MB
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' # type: ignore

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Usuario, int(user_id))

# ---------- Confirmação de e-mail ----------
# Na Vercel o link do e-mail precisa ser https
app.config['PREFERRED_URL_SCHEME'] = 'https' if os.environ.get('VERCEL') else 'http'
_serializador = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='confirmar-email')
VALIDADE_TOKEN_SEGUNDOS = 60 * 60 * 24  # o link vale 24 horas

def gerar_token_email(email):
    return _serializador.dumps(email)

def ler_token_email(token):
    try:
        return _serializador.loads(token, max_age=VALIDADE_TOKEN_SEGUNDOS)
    except (SignatureExpired, BadSignature):
        return None

def enviar_email_confirmacao(usuario):
    """Envia o link de confirmação. Devolve True se enviou, False se deu erro."""
    remetente = os.environ.get('MAIL_USER')
    senha = os.environ.get('MAIL_SENHA')
    if not remetente or not senha:
        app.logger.error('MAIL_USER / MAIL_SENHA não configurados.')
        return False

    link = url_for('confirmar_email', token=gerar_token_email(usuario.email), _external=True)
    msg = EmailMessage()
    msg['Subject'] = 'Confirme seu e-mail - Gerenciador de Tarefas'
    msg['From'] = remetente
    msg['To'] = usuario.email
    msg.set_content(
        f'Olá, {usuario.nome}!\n\n'
        f'Para ativar sua conta, abra o link abaixo (vale por 24 horas):\n{link}\n\n'
        'Se não foi você que criou a conta, ignore este e-mail.'
    )
    msg.add_alternative(
        f'<p>Olá, {escape(usuario.nome)}!</p>'
        '<p>Para ativar sua conta, clique no botão abaixo (vale por 24 horas):</p>'
        f'<p><a href="{link}" style="background:#4f46e5;color:#fff;padding:12px 20px;'
        'border-radius:8px;text-decoration:none;display:inline-block">Confirmar e-mail</a></p>'
        f'<p style="color:#666;font-size:13px">Ou copie este link: {link}</p>'
        '<p style="color:#666;font-size:13px">Se não foi você que criou a conta, ignore este e-mail.</p>',
        subtype='html',
    )
    try:
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(remetente, senha)
            smtp.send_message(msg)
        return True
    except Exception as e:
        app.logger.error(f'Falha ao enviar e-mail de confirmação: {e}')
        return False

# Redefinição de senha 
_serializador_senha = URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='redefinir-senha')
VALIDADE_TOKEN_SENHA_SEGUNDOS = 60 * 60  # o link vale 1 hora
TAMANHO_MIN_SENHA = 6

def gerar_token_senha(usuario):
    # Guarda um pedaço do hash da senha atual: assim que a senha muda, o link antigo deixa de valer.
    return _serializador_senha.dumps({'id': usuario.id, 'v': usuario.senha[-12:]})

def ler_token_senha(token):
    """Devolve o usuário dono do token, ou None se o link for inválido/expirado/já usado."""
    try:
        dados = _serializador_senha.loads(token, max_age=VALIDADE_TOKEN_SENHA_SEGUNDOS)
    except (SignatureExpired, BadSignature):
        return None
    usuario = db.session.get(Usuario, dados.get('id')) if isinstance(dados, dict) else None
    if not usuario or usuario.senha[-12:] != dados.get('v'):
        return None
    return usuario

def validar_nova_senha(nova, confirmar):
    """Devolve a mensagem de erro, ou None se a senha é válida."""
    if len(nova) < TAMANHO_MIN_SENHA:
        return f'A nova senha precisa ter pelo menos {TAMANHO_MIN_SENHA} caracteres.'
    if nova != confirmar:
        return 'A confirmação não bate com a nova senha.'
    return None

def enviar_email_redefinicao(usuario):
    """Envia o link para criar uma nova senha. Devolve True se enviou, False se deu erro."""
    remetente = os.environ.get('MAIL_USER')
    senha = os.environ.get('MAIL_SENHA')
    if not remetente or not senha:
        app.logger.error('MAIL_USER / MAIL_SENHA não configurados.')
        return False

    link = url_for('redefinir_senha', token=gerar_token_senha(usuario), _external=True)
    msg = EmailMessage()
    msg['Subject'] = 'Redefinir sua senha - Gerenciador de Tarefas'
    msg['From'] = remetente
    msg['To'] = usuario.email
    msg.set_content(
        f'Olá, {usuario.nome}!\n\n'
        f'Para criar uma nova senha, abra o link abaixo (vale por 1 hora):\n{link}\n\n'
        'Se não foi você que pediu, ignore este e-mail: sua senha continua a mesma.'
    )
    msg.add_alternative(
        f'<p>Olá, {escape(usuario.nome)}!</p>'
        '<p>Para criar uma nova senha, clique no botão abaixo (vale por 1 hora):</p>'
        f'<p><a href="{link}" style="background:#4f46e5;color:#fff;padding:12px 20px;'
        'border-radius:8px;text-decoration:none;display:inline-block">Criar nova senha</a></p>'
        f'<p style="color:#666;font-size:13px">Ou copie este link: {link}</p>'
        '<p style="color:#666;font-size:13px">Se não foi você que pediu, ignore este e-mail: sua senha continua a mesma.</p>',
        subtype='html',
    )
    try:
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(remetente, senha)
            smtp.send_message(msg)
        return True
    except Exception as e:
        app.logger.error(f'Falha ao enviar e-mail de redefinição de senha: {e}')
        return False

# Cria função do link para google agenda
def link_google_calendar(tarefa):
    if not tarefa.prazo:
        return "#"
    inicio = tarefa.prazo.strftime('%Y%m%dT%H%M00')
    fim = (tarefa.prazo + timedelta(hours=1)).strftime('%Y%m%dT%H%M00')
    
    titulo = quote(tarefa.titulo)
    descricao = quote(tarefa.descricao or '')
    
    return f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={titulo}&dates={inicio}/{fim}&details={descricao}"

# Deixa a função disponível nos templates
app.jinja_env.globals.update(link_google_calendar=link_google_calendar)

@app.context_processor
def injetar_categorias_globais():
    if current_user.is_authenticated:
        return dict(categorias_globais=categorias_acessiveis())
    return dict(categorias_globais=[])

@app.context_processor
def injetar_notificacoes():
    if not current_user.is_authenticated:
        return dict(n_notificacoes=0)
    n = (Contato.query.filter_by(destinatario_id=current_user.id, status='pendente').count()
         + ConviteEquipe.query.filter_by(convidado_id=current_user.id).count()
         + Tarefa.query.filter_by(responsavel_id=current_user.id, aceite='aguardando').count())
    return dict(n_notificacoes=n)


def validar_prazo(valor):
    valor = (valor or '').strip()
    if not valor:
        return None
    try:
        # Lê no formato brasileiro que o Flatpickr envia (dd/mm/aaaa HH:MM)
        prazo = datetime.strptime(valor, '%d/%m/%Y %H:%M')
    except ValueError:
        try:
            # Fallback para o formato ISO caso venha de outra tela
            prazo = datetime.strptime(valor, '%Y-%m-%d %H:%M')
        except ValueError:
            raise ValueError('Data e hora do prazo inválidas')

    return prazo


def tarefa_atrasada(tarefa):
    if tarefa.prazo is None:
        return False
    if tarefa.status in ['Concluída', 'Cancelada']:
        return False
    return tarefa.prazo < agora_local()

LIMITE_TAREFAS_PENDENTES_POR_CONTATO = 5
LIMITE_PEDIDOS_PENDENTES = 10

def buscar_vinculo(a_id, b_id):
    return Contato.query.filter(or_(
        and_(Contato.solicitante_id == a_id, Contato.destinatario_id == b_id),
        and_(Contato.solicitante_id == b_id, Contato.destinatario_id == a_id)
    )).first()

def sao_contatos(outro_id):
    if not outro_id:
        return False
    v = buscar_vinculo(current_user.id, outro_id)
    return v is not None and v.status == 'aceito'

def contatos_aceitos():
    vinculos = Contato.query.filter(
        Contato.status == 'aceito',
        or_(Contato.solicitante_id == current_user.id, Contato.destinatario_id == current_user.id)
    ).all()
    ids = [c.destinatario_id if c.solicitante_id == current_user.id else c.solicitante_id for c in vinculos]
    if not ids:
        return []
    return Usuario.query.filter(Usuario.id.in_(ids)).order_by(Usuario.nomeUsuario).all()

def limpar_vinculos(a_id, b_id):
    """Ao remover um contato: apaga o que ainda estava pendente entre os dois e os compartilhamentos."""
    Tarefa.query.filter(
        Tarefa.equipe_id.is_(None),
        Tarefa.aceite == 'aguardando',
        or_(and_(Tarefa.criador_id == a_id, Tarefa.responsavel_id == b_id),
            and_(Tarefa.criador_id == b_id, Tarefa.responsavel_id == a_id))
    ).delete(synchronize_session=False)

    ConviteEquipe.query.filter(or_(
        and_(ConviteEquipe.convidante_id == a_id, ConviteEquipe.convidado_id == b_id),
        and_(ConviteEquipe.convidante_id == b_id, ConviteEquipe.convidado_id == a_id)
    )).delete(synchronize_session=False)

    compartilhamentos = CategoriaCompartilhada.query.join(Categoria).filter(or_(
        and_(Categoria.usuario_id == a_id, CategoriaCompartilhada.usuario_id == b_id),
        and_(Categoria.usuario_id == b_id, CategoriaCompartilhada.usuario_id == a_id)
    )).all()
    for cs in compartilhamentos:
        db.session.delete(cs)

def eh_membro(equipe):
    return any(m.usuario_id == current_user.id for m in equipe.membros)

def eh_dono(equipe):
    return equipe.dono_id == current_user.id

def membro_da_equipe(equipe, usuario_id=None):
    uid = current_user.id if usuario_id is None else usuario_id
    return next((m for m in equipe.membros if m.usuario_id == uid), None)

def eh_admin_equipe(equipe):
    """Criador ou membro promovido a admin da equipe."""
    if eh_dono(equipe):
        return True
    m = membro_da_equipe(equipe)
    return m is not None and m.cargo == 'admin'

def garantir_schema():
    """Cria as tabelas e acrescenta colunas novas que faltem (funciona em SQLite e Postgres)."""
    db.create_all()
    binario = 'BLOB' if db.engine.dialect.name == 'sqlite' else 'BYTEA'
    verdadeiro = '1' if db.engine.dialect.name == 'sqlite' else 'TRUE'   # <- NOVA
    novas = [
        ('usuario', 'email_verificado', f'BOOLEAN NOT NULL DEFAULT {verdadeiro}'),   # <- NOVA
        ('membro_equipe', 'cargo', "VARCHAR(20) NOT NULL DEFAULT 'membro'"),
        ('usuario', 'foto_dados', binario),
        ('usuario', 'foto_tipo', 'VARCHAR(50)'),
    ]
    insp = inspect(db.engine)
    for tabela, coluna, tipo in novas:
        existentes = [c['name'] for c in insp.get_columns(tabela)]
        if coluna not in existentes:
            db.session.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}"))
            db.session.commit()

def gerar_codigo():
    return secrets.token_hex(3).upper()

CHAVES_FILTRO = ['q', 'status', 'prioridade', 'prazo', 'responsavel', 'categoria', 'equipe']

def filtro_ativo():
    return any(request.args.get(k) for k in CHAVES_FILTRO)

def filtrar_tarefas(tarefas):
    q = request.args.get('q', '').strip().lower()
    status = request.args.get('status', '')
    prioridade = request.args.get('prioridade', '')
    prazo = request.args.get('prazo', '')
    responsavel = request.args.get('responsavel', '')
    categoria = request.args.get('categoria', '')
    agora = agora_local()

    resultado = []
    for t in tarefas:
        if q and q not in (t.titulo or '').lower() and q not in (t.descricao or '').lower():
            continue
        if status and t.status != status:
            continue
        if prioridade and (t.prioridade or 'A definir') != prioridade:
            continue
        if responsavel and str(t.responsavel_id) != responsavel:
            continue
        minha_categoria = t.categoria_id if t.criador_id == current_user.id else None
        if categoria == 'nenhuma':
            if minha_categoria is not None:
                continue
        elif categoria and str(minha_categoria) != categoria:
            continue
        if prazo == 'atrasadas' and not tarefa_atrasada(t):
            continue
        if prazo == 'hoje' and not (t.prazo and t.prazo.date() == agora.date()):
            continue
        if prazo == 'semana' and not (t.prazo and agora <= t.prazo <= agora + timedelta(days=7)):
            continue
        if prazo == 'sem_prazo' and t.prazo is not None:
            continue
        resultado.append(t)
    return resultado

def categorias_do_usuario():
    return Categoria.query.filter_by(usuario_id=current_user.id).order_by(Categoria.nome).all()

def categorias_acessiveis():
    """Minhas categorias + as que outros compartilharam comigo."""
    proprias = categorias_do_usuario()
    de_outros = [cs.categoria for cs in CategoriaCompartilhada.query.filter_by(usuario_id=current_user.id).all()]
    return proprias + sorted(de_outros, key=lambda c: c.nome.lower())

def categoria_acessivel(categoria):
    if categoria.usuario_id == current_user.id:
        return True
    return CategoriaCompartilhada.query.filter_by(
        categoria_id=categoria.id, usuario_id=current_user.id
    ).first() is not None

def membros_da_categoria(categoria):
    return [categoria.dono] + [cs.usuario for cs in categoria.compartilhamentos]

def categoria_valida(valor):
    try:
        cid = int(valor)
    except (TypeError, ValueError):
        return None
    return cid if cid in {c.id for c in categorias_acessiveis()} else None

def tarefas_individuais():
    todas = Tarefa.query.filter(
        Tarefa.criador_id == current_user.id,
        Tarefa.responsavel_id == current_user.id,
        Tarefa.equipe_id.is_(None)
    ).all()
    return [t for t in todas if t.categoria is None or t.categoria.usuario_id == current_user.id]

def contar_status(tarefas_lista):
    contagem = {'Pendente': 0, 'Em andamento': 0, 'Concluída': 0, 'Cancelada': 0}
    for t in tarefas_lista:
        if t.status in contagem:
            contagem[t.status] += 1
    return list(contagem.values())
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
    if pode_editar(tarefa):
        return True
    return current_user.id == tarefa.responsavel_id and tarefa.aceite == 'aceita'

def proximo_seguro():
    prox = request.form.get('next', '')
    if prox.startswith('/') and not prox.startswith('//') and '\\' not in prox:
        return prox
    return None

def voltar_para_lista(equipe_id=None):
    prox = proximo_seguro()
    if prox:
        return redirect(prox)
    if equipe_id:
        return redirect(url_for('ver_equipe', equipe_id=equipe_id))
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

        existentes = Usuario.query.filter((Usuario.email == email) | (Usuario.nomeUsuario == nomeUsuario)).all()
        if any(u.email_verificado for u in existentes):
            flash('Já existe um usuário com esse email ou nome de usuário.', 'danger')
            return redirect(url_for('registro'))

        # Contas que nunca confirmaram o e-mail não conseguem entrar (não têm dados),
        # então liberamos o e-mail/usuário para um novo cadastro (ex.: digitou o e-mail errado).
        if existentes:
            try:
                for u in existentes:
                    db.session.delete(u)
                db.session.commit()
            except Exception:
                db.session.rollback()
                flash('Já existe um usuário com esse email ou nome de usuário.', 'danger')
                return redirect(url_for('registro'))

        novo_usuario = Usuario(nomeUsuario=nomeUsuario, nome=nome, email=email, senha=senha, email_verificado=False) # type: ignore
        db.session.add(novo_usuario)
        db.session.commit()

        if enviar_email_confirmacao(novo_usuario):
            flash(f'Conta criada! Enviamos um link de confirmação para {email}. Confirme para poder entrar.', 'success')
        else:
            flash('Conta criada, mas não conseguimos enviar o e-mail agora. Tente entrar para pedir um novo link.', 'danger')
        return redirect(url_for('login'))

    return render_template('registro.html')

@app.route('/confirmar/<token>')
def confirmar_email(token):
    email = ler_token_email(token)
    usuario = Usuario.query.filter_by(email=email).first() if email else None
    if not usuario:
        flash('Link inválido ou expirado. Tente entrar para receber um novo link.', 'danger')
        return redirect(url_for('login'))

    if not usuario.email_verificado:
        usuario.email_verificado = True
        db.session.commit()
    flash('E-mail confirmado! Agora você já pode entrar.', 'success')
    return redirect(url_for('login'))

@app.route('/reenviar_confirmacao', methods=['POST'])
def reenviar_confirmacao():
    email = request.form.get('email', '').strip().lower()
    usuario = Usuario.query.filter_by(email=email).first()
    if usuario and not usuario.email_verificado:
        enviar_email_confirmacao(usuario)
    flash('Se houver uma conta aguardando confirmação nesse e-mail, enviamos um novo link.', 'success')
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identificador = request.form['identificador'].strip()
        senha = request.form['senha']

        usuario = Usuario.query.filter(
            (Usuario.email == identificador.lower()) | (Usuario.nomeUsuario == identificador)
        ).first()

        if usuario and check_password_hash(usuario.senha, senha):
            if not usuario.email_verificado:
                flash('Confirme seu e-mail antes de entrar. Veja sua caixa de entrada (e o spam).', 'danger')
                return render_template('login.html', reenviar_email=usuario.email)
            login_user(usuario)
            flash('Login realizado com sucesso!', 'success')
            return redirect(url_for('admin_dashboard') if usuario.cargo == 'admin' else url_for('quadro'))
        else:
            flash('Usuário/e-mail ou senha incorretos.', 'danger')

    return render_template('login.html')

@app.route('/esqueci_senha', methods=['GET', 'POST'])
def esqueci_senha():
    if current_user.is_authenticated:
        return redirect(url_for('perfil'))
    if request.method == 'POST':
        identificador = request.form.get('identificador', '').strip()
        usuario = Usuario.query.filter(
            (Usuario.email == identificador.lower()) | (Usuario.nomeUsuario == identificador)
        ).first() if identificador else None
        if usuario:
            if usuario.email_verificado:
                enviar_email_redefinicao(usuario)
            else:
                # conta que nunca confirmou o e-mail: manda o link de confirmação no lugar
                enviar_email_confirmacao(usuario)
        # Mesma resposta exista a conta ou não, para não revelar quem tem cadastro.
        flash('Se existir uma conta com esses dados, enviamos um link para o e-mail cadastrado. Veja também o spam.', 'success')
        return redirect(url_for('login'))
    return render_template('esqueci_senha.html')

@app.route('/redefinir_senha/<token>', methods=['GET', 'POST'])
def redefinir_senha(token):
    usuario = ler_token_senha(token)
    if not usuario:
        flash('Link inválido ou expirado. Peça um novo.', 'danger')
        return redirect(url_for('esqueci_senha'))

    if request.method == 'POST':
        nova = request.form.get('senha', '')
        erro = validar_nova_senha(nova, request.form.get('confirmar_senha', ''))
        if erro:
            flash(erro, 'danger')
            return render_template('redefinir_senha.html', token=token)
        usuario.senha = generate_password_hash(nova)
        db.session.commit()
        flash('Senha alterada! Agora você já pode entrar.', 'success')
        return redirect(url_for('login'))

    return render_template('redefinir_senha.html', token=token)

#admin
@app.route('/admin')
@login_required
def admin_dashboard():
    if not eh_admin():
        flash("Acesso negado!", 'danger')
        return redirect(url_for('quadro'))

    tarefas = Tarefa.query.all()
    return render_template('quadro_admin.html', tarefas = tarefas)

#adicionar tarefa via modal
STATUS_VALIDOS = ['Pendente', 'Em andamento', 'Concluída', 'Cancelada']
PRIORIDADES_VALIDAS = ['Alta', 'Média', 'Baixa', 'A definir']

@app.route('/adicionar_tarefa', methods=['GET', 'POST'])
@login_required
def adicionar_tarefa():
    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        descricao = request.form.get('descricao', '').strip()
        status = 'Pendente'
        prioridade = request.form.get('prioridade', 'A definir')

        if not titulo:
            flash('O título da tarefa é obrigatório.', 'danger')
            return redirect(request.referrer or url_for('quadro'))

        if prioridade not in PRIORIDADES_VALIDAS:
            flash('Prioridade inválida.', 'danger')
            return redirect(request.referrer or url_for('quadro'))

        try:
            prazo = validar_prazo(request.form.get('prazo'))
        except ValueError as e:
            flash(str(e), 'danger')
            return redirect(request.referrer or url_for('quadro'))

        responsavel_id = current_user.id
        categoria_id = categoria_valida(request.form.get('categoria_id'))

        nova_tarefa = Tarefa(
            titulo=titulo, 
            descricao=descricao, 
            status=status, 
            prioridade=prioridade, 
            prazo=prazo, 
            criador_id=current_user.id, 
            responsavel_id=responsavel_id, 
            categoria_id=categoria_id
        )

        db.session.add(nova_tarefa)
        db.session.flush()

        # Adiciona as subtarefas enviadas no checklist opcional
        for subtitulo in request.form.getlist('subtarefas[]'):
            if subtitulo.strip():
                sub = Subtarefa(tarefa_id=nova_tarefa.id, titulo=subtitulo.strip())
                db.session.add(sub)

        db.session.commit()

        flash('Tarefa adicionada com sucesso!', 'success')
        return redirect(request.referrer or url_for('quadro'))

    return redirect(request.referrer or url_for('quadro'))

@app.route('/subtarefas/<int:subtarefa_id>/toggle', methods=['POST'])
@login_required
def toggle_subtarefa(subtarefa_id):
    sub = db.get_or_404(Subtarefa, subtarefa_id)
    sub.concluida = not sub.concluida
    db.session.commit()
    return {'success': True, 'concluida': sub.concluida}

#editar tarefa
@app.route('/editar_tarefa/<int:tarefa_id>', methods=['POST'])
@login_required
def editar_tarefa(tarefa_id):
    tarefa = db.get_or_404(Tarefa, tarefa_id)

    if not pode_mudar_status(tarefa):
        flash('Você não tem permissão para editar esta tarefa.', 'danger')
        return voltar_para_lista(tarefa.equipe_id)

    status = request.form.get('status')
    if status in STATUS_VALIDOS:
        tarefa.status = status

    if pode_editar(tarefa):
        prioridade = request.form.get('prioridade', tarefa.prioridade or 'A definir')
        if prioridade in PRIORIDADES_VALIDAS:
            tarefa.prioridade = prioridade

        try:
            prazo = validar_prazo(request.form.get('prazo'))
            tarefa.prazo = prazo
        except ValueError as e:
            flash(str(e), 'danger')
            return redirect(request.referrer or url_for('quadro'))

        if tarefa.criador_id == current_user.id and not tarefa.equipe_id:
            tarefa.categoria_id = categoria_valida(request.form.get('categoria_id'))

        titulo = request.form.get('titulo', '').strip()
        descricao = request.form.get('descricao', '').strip()
        if titulo:
            tarefa.titulo = titulo
        tarefa.descricao = descricao

        # 📋 Sincronização e salvamento do Checklist na Edição
        ids_enviados = request.form.getlist('subtarefa_ids[]')
        titulos_enviados = request.form.getlist('subtarefas_titulos[]')

        # Mapeia subtarefas atuais da tarefa
        subtarefas_atuais = {sub.id: sub for sub in tarefa.subtarefas}
        ids_processados = []

        for sub_id, titulo_sub in zip(ids_enviados, titulos_enviados):
            titulo_sub = titulo_sub.strip()
            if not titulo_sub:
                continue
            
            if sub_id != 'new' and int(sub_id) in subtarefas_atuais:
                # Atualiza título da subtarefa existente
                s_obj = subtarefas_atuais[int(sub_id)]
                s_obj.titulo = titulo_sub
                ids_processados.append(s_obj.id)
            else:
                # Adiciona nova subtarefa
                nova_sub = Subtarefa(tarefa_id=tarefa.id, titulo=titulo_sub, concluida=False)
                db.session.add(nova_sub)

        # Remove subtarefas que foram deletadas na interface
        for s_id, s_obj in subtarefas_atuais.items():
            if s_id not in ids_processados:
                db.session.delete(s_obj)

    db.session.commit()
    flash('Tarefa atualizada com sucesso!', 'success')
    return redirect(request.referrer or url_for('quadro'))

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
    # Verifica se o usuário escolheu uma nova ordenação na requisição
    nova_ordenacao = request.args.get('ordenacao')
    if nova_ordenacao:
        current_user.ordenacao_quadro = nova_ordenacao
        db.session.commit()

    equipes_usuario = [m.equipe for m in MembroEquipe.query.filter_by(usuario_id=current_user.id).all()]
    filtro_equipe = request.args.get('equipe', 'todas')

    if filtro_equipe == 'minhas':
        base_tarefas = Tarefa.query.filter(
            Tarefa.responsavel_id == current_user.id,
            Tarefa.equipe_id.is_(None),
            Tarefa.aceite == 'aceita'
        ).all()
    elif filtro_equipe != 'todas' and filtro_equipe.isdigit():
        eq_id = int(filtro_equipe)
        base_tarefas = Tarefa.query.filter_by(equipe_id=eq_id).all()
    else:
        ids_equipes = [e.id for e in equipes_usuario]
        tarefas_indiv = Tarefa.query.filter(
            Tarefa.responsavel_id == current_user.id,
            Tarefa.equipe_id.is_(None),
            Tarefa.aceite == 'aceita'
        ).all()
        tarefas_eqp = Tarefa.query.filter(Tarefa.equipe_id.in_(ids_equipes)).all() if ids_equipes else []
        base_tarefas = list({t.id: t for t in (tarefas_indiv + tarefas_eqp)}.values())

    tarefas = filtrar_tarefas(base_tarefas)

    # Lógica de Ordenação persistida
    ordem = current_user.ordenacao_quadro
    if ordem == 'prioridade_desc':
        peso_prio = {'Alta': 1, 'Média': 2, 'Baixa': 3, 'A definir': 4}
        tarefas.sort(key=lambda t: peso_prio.get(t.prioridade, 5))
    elif ordem == 'prioridade_asc':
        peso_prio = {'Baixa': 1, 'Média': 2, 'Alta': 3, 'A definir': 4}
        tarefas.sort(key=lambda t: peso_prio.get(t.prioridade, 5))
    elif ordem == 'prazo':
        tarefas.sort(key=lambda t: (t.prazo is None, t.prazo))
    elif ordem == 'titulo':
        tarefas.sort(key=lambda t: t.titulo.lower())
    elif ordem == 'status':
        peso_status = {'Pendente': 1, 'Em andamento': 2, 'Concluída': 3, 'Cancelada': 4}
        tarefas.sort(key=lambda t: peso_status.get(t.status, 5))
        
    minhas = Tarefa.query.filter(
        Tarefa.responsavel_id == current_user.id,
        Tarefa.equipe_id.is_(None),
        Tarefa.aceite == 'aceita'
    ).all()
    tarefas = filtrar_tarefas(minhas)
    return render_template('quadro.html',
                           tarefas=tarefas,
                           grafico=contar_status(tarefas),
                           categorias=categorias_do_usuario(),
                           equipes_usuario=equipes_usuario,
                           equipe_atual=filtro_equipe,
                           filtrando=filtro_ativo(),
                           ordenacao_atual=ordem)

#rota das equipes
@app.route('/equipes')
@login_required
def equipes():
    minhas = Equipe.query.filter_by(dono_id=current_user.id).all()
    participo = (Equipe.query.join(MembroEquipe, MembroEquipe.equipe_id == Equipe.id)).filter(MembroEquipe.usuario_id == current_user.id, Equipe.dono_id != current_user.id).all()
    return render_template('equipes.html', minhas=minhas, participo=participo)

#criar equipe
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
    db.session.add(MembroEquipe(equipe_id=equipe.id, usuario_id=current_user.id, cargo='admin'))
    db.session.commit()
    flash('Equipe criada!', 'success')
    return redirect(url_for('ver_equipe', equipe_id=equipe.id))

#entrar equipe
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

#ver equipe
@app.route('/equipes/<int:equipe_id>')
@login_required
def ver_equipe(equipe_id):
    equipe = db.get_or_404(Equipe, equipe_id)
    if not eh_membro(equipe):
        flash('Você não faz parte dessa equipe.', 'danger')
        return redirect(url_for('equipes'))
    tarefas = filtrar_tarefas(Tarefa.query.filter_by(equipe_id=equipe.id).all())

    convidaveis = []
    total_contatos = 0
    admin_equipe = eh_admin_equipe(equipe)
    if admin_equipe:
        ja = {m.usuario_id for m in equipe.membros} | {c.convidado_id for c in equipe.convites}
        meus_contatos = contatos_aceitos()
        total_contatos = len(meus_contatos)
        convidaveis = [u for u in meus_contatos if u.id not in ja]

    return render_template('equipe.html', equipe=equipe, tarefas=tarefas,
                           membros=equipe.membros, dono=eh_dono(equipe),
                           admin_equipe=admin_equipe,
                           grafico=contar_status(tarefas),
                           pessoas=[m.usuario for m in equipe.membros],
                           filtrando=filtro_ativo(),
                           convidaveis=convidaveis,
                           total_contatos=total_contatos)

#adicionar tarefa equipe
@app.route('/equipes/<int:equipe_id>/adicionar_tarefa', methods=['GET', 'POST'])
@login_required
def adicionar_tarefa_equipe(equipe_id):
    equipe = db.get_or_404(Equipe, equipe_id)
    if not eh_admin_equipe(equipe):
        flash('Só o criador ou um admin da equipe pode atribuir tarefas.', 'danger')
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
        db.session.flush()

        for subtitulo in request.form.getlist('subtarefas[]'):
            if subtitulo.strip():
                sub = Subtarefa(tarefa_id=nova_tarefa.id, titulo=subtitulo.strip())
                db.session.add(sub)

        db.session.commit()  # <--- 3. Salva tudo no banco de dados de uma vez

        flash('Tarefa atribuida!', 'success')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))

    return render_template('adicionar_tarefa_equipe.html', equipe=equipe, membros=membros, agora=agora_local())

#gerar codigo da equipe
@app.route('/equipes/<int:equipe_id>/novo_codigo', methods=['POST'])
@login_required
def novo_codigo_equipe(equipe_id):
    equipe = db.get_or_404(Equipe, equipe_id)
    if not eh_admin_equipe(equipe):
        flash('Só o criador ou um admin da equipe pode gerar um novo código.', 'danger')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))
    equipe.codigo_acesso = gerar_codigo()
    db.session.commit()
    flash('Novo código gerado. O anterior não vale mais.', 'success')
    return redirect(url_for('ver_equipe', equipe_id=equipe.id))

#remover usuario da equipe
@app.route('/equipes/<int:equipe_id>/remover/<int:usuario_id>', methods=['POST'])
@login_required
def remover_membro(equipe_id, usuario_id):
    equipe = db.get_or_404(Equipe, equipe_id)
    sair = usuario_id == current_user.id
    if usuario_id == equipe.dono_id:
        flash('O criador da equipe não pode ser removido.', 'danger')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))
    if sair and eh_dono(equipe):
        flash('O criador não pode sair da própria equipe. Exclua a equipe se quiser encerrá-la.', 'danger')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))
    if not sair and not eh_admin_equipe(equipe):
        flash('Só o criador ou um admin da equipe pode remover membros.', 'danger')
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

#excluir equipe
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

#promover ou rebaixar admin da equipe (somente o criador)
@app.route('/equipes/<int:equipe_id>/membros/<int:usuario_id>/cargo', methods=['POST'])
@login_required
def definir_cargo_membro(equipe_id, usuario_id):
    equipe = db.get_or_404(Equipe, equipe_id)
    if not eh_dono(equipe):
        flash('Só o criador da equipe pode promover ou remover admins.', 'danger')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))
    if usuario_id == equipe.dono_id:
        flash('O criador da equipe já tem todos os poderes.', 'info')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))

    cargo = request.form.get('cargo', '')
    if cargo not in ('admin', 'membro'):
        flash('Cargo inválido.', 'danger')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))

    membro = MembroEquipe.query.filter_by(equipe_id=equipe.id, usuario_id=usuario_id).first_or_404()
    membro.cargo = cargo
    db.session.commit()
    if cargo == 'admin':
        flash(f'{membro.usuario.nomeUsuario} agora é admin da equipe.', 'success')
    else:
        flash(f'{membro.usuario.nomeUsuario} não é mais admin da equipe.', 'success')
    return redirect(url_for('ver_equipe', equipe_id=equipe.id))

# Entrega a foto de perfil que está no banco (os templates continuam usando static/uploads/<nome>)
@app.route('/static/uploads/<nome>')
def foto_upload(nome):
    usuario = Usuario.query.filter_by(foto_perfil=nome).first()
    if not usuario or not usuario.foto_dados:
        abort(404)
    resp = Response(usuario.foto_dados, mimetype=usuario.foto_tipo or 'image/jpeg')
    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return resp

@app.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    if request.method == 'POST':
        current_user.nome = request.form.get('nome', '').strip()
        novo_nome_usuario = request.form.get('nomeUsuario', '').strip()
        
        # Valiza se o nome de usuário foi preenchido
        if not novo_nome_usuario:
            flash('O nome de usuário não pode ficar vazio.', 'danger')
            return redirect(url_for('perfil'))

        # Se o usuário alterou o nome de usuário, verifica se já existe no banco
        if novo_nome_usuario != current_user.nomeUsuario:
            usuario_existente = Usuario.query.filter_by(nomeUsuario=novo_nome_usuario).first()
            if usuario_existente:
                flash('Este nome de usuário já está em uso por outro usuário.', 'danger')
                return redirect(url_for('perfil'))
            current_user.nomeUsuario = novo_nome_usuario

        # Tratamento de upload da foto de perfil (mantém igual)
        if 'foto_perfil' in request.files:
            file = request.files['foto_perfil']
            if file and file.filename != '' and arquivo_permitido(file.filename):
                dados = file.read()
                if len(dados) > TAMANHO_MAX_FOTO:
                    flash('A foto é grande demais (máximo 1 MB).', 'danger')
                    return redirect(request.referrer or url_for('quadro'))
                filename = secure_filename(f"user_{current_user.id}_{int(agora_local().timestamp())}_{file.filename}")
                current_user.foto_perfil = filename
                current_user.foto_dados = dados
                current_user.foto_tipo = file.mimetype or 'image/jpeg'

        db.session.commit()
        flash('Perfil atualizado com sucesso!', 'success')
        return redirect(request.referrer or url_for('quadro'))

    return render_template('perfil.html')

@app.route('/perfil/senha', methods=['POST'])
@login_required
def alterar_senha():
    atual = request.form.get('senha_atual', '')
    nova = request.form.get('senha_nova', '')
    if not check_password_hash(current_user.senha, atual):
        flash('A senha atual está incorreta.', 'danger')
        return redirect(url_for('perfil'))
    erro = validar_nova_senha(nova, request.form.get('senha_confirmar', ''))
    if erro:
        flash(erro, 'danger')
        return redirect(url_for('perfil'))
    if check_password_hash(current_user.senha, nova):
        flash('A nova senha precisa ser diferente da atual.', 'danger')
        return redirect(url_for('perfil'))
    current_user.senha = generate_password_hash(nova)
    db.session.commit()
    flash('Senha alterada com sucesso!', 'success')
    return redirect(url_for('perfil'))

def apagar_dados_do_usuario(uid):
    """Remove o usuário e tudo que depende dele. Não faz commit (quem chama faz)."""
    # 1) Equipes que ele criou: passa o comando para outro membro; se não há ninguém, apaga a equipe.
    for equipe in Equipe.query.filter_by(dono_id=uid).all():
        outros = [m for m in equipe.membros if m.usuario_id != uid]
        if outros:
            novo_dono = next((m for m in outros if m.cargo == 'admin'), outros[0])
            novo_dono.cargo = 'admin'
            equipe.dono_id = novo_dono.usuario_id
        else:
            for t in list(equipe.tarefas):
                db.session.delete(t)
            db.session.delete(equipe)  # membros e convites caem junto (cascade)
    db.session.flush()

    # 2) Tarefas de equipe: as dele passam para o criador da equipe (as pendentes ficam "Cancelada",
    #    igual a quando alguém sai da equipe).
    for t in Tarefa.query.filter(Tarefa.equipe_id.isnot(None),
                                 or_(Tarefa.criador_id == uid, Tarefa.responsavel_id == uid)).all():
        dono = t.equipe.dono_id
        if t.responsavel_id == uid:
            if t.status != 'Concluída':
                t.status = 'Cancelada'
            t.responsavel_id = dono
        if t.criador_id == uid:
            t.criador_id = dono

    # 3) Tarefas pessoais: as que ele enviou para um contato ficam com o contato; o resto é apagado.
    for t in Tarefa.query.filter(Tarefa.equipe_id.is_(None),
                                 or_(Tarefa.criador_id == uid, Tarefa.responsavel_id == uid)).all():
        if t.criador_id == uid and t.responsavel_id != uid:
            t.criador_id = t.responsavel_id
        else:
            db.session.delete(t)  # pelo ORM, para apagar as subtarefas junto
    db.session.flush()

    # 4) Categorias dele (tarefas de outras pessoas nelas só perdem a categoria)
    for c in Categoria.query.filter_by(usuario_id=uid).all():
        Tarefa.query.filter_by(categoria_id=c.id).update({'categoria_id': None})
        db.session.delete(c)  # os compartilhamentos caem junto (cascade)
    db.session.flush()

    # 5) Vínculos soltos e, por fim, o usuário
    CategoriaCompartilhada.query.filter_by(usuario_id=uid).delete()
    ConviteEquipe.query.filter(or_(ConviteEquipe.convidado_id == uid, ConviteEquipe.convidante_id == uid)).delete()
    MembroEquipe.query.filter_by(usuario_id=uid).delete()
    Contato.query.filter(or_(Contato.solicitante_id == uid, Contato.destinatario_id == uid)).delete()
    Usuario.query.filter_by(id=uid).delete()

@app.route('/perfil/excluir', methods=['POST'])
@login_required
def excluir_conta():
    if not check_password_hash(current_user.senha, request.form.get('senha', '')):
        flash('Senha incorreta. Sua conta não foi excluída.', 'danger')
        return redirect(url_for('perfil'))
    if current_user.cargo == 'admin' and Usuario.query.filter_by(cargo='admin').count() <= 1:
        flash('Você é o único administrador do sistema, então a conta não pode ser excluída.', 'danger')
        return redirect(url_for('perfil'))

    uid = current_user.id
    try:
        apagar_dados_do_usuario(uid)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'Falha ao excluir a conta {uid}: {e}')
        flash('Não foi possível excluir a conta agora. Tente de novo.', 'danger')
        return redirect(url_for('perfil'))

    logout_user()
    flash('Sua conta foi excluída. Sentiremos sua falta!', 'success')
    return redirect(url_for('login'))

#criar categoria
@app.route('/categorias/criar', methods=['POST'])
@login_required
def criar_categoria():
    nome = request.form.get('nome', '').strip()[:50]
    if not nome:
        flash('Dê um nome para a categoria.', 'danger')
        return redirect(url_for('ver_categorias'))
    if any(c.nome.lower() == nome.lower() for c in categorias_do_usuario()):
        flash('Você já tem uma categoria com esse nome.', 'danger')
        return redirect(url_for('ver_categorias'))
    db.session.add(Categoria(nome=nome, usuario_id=current_user.id))  # type: ignore
    db.session.commit()
    flash('Categoria criada.', 'success')
    return redirect(url_for('ver_categorias'))

#excluir categoria
@app.route('/categorias/<int:categoria_id>/excluir', methods=['POST'])
@login_required
def excluir_categoria(categoria_id):
    categoria = db.get_or_404(Categoria, categoria_id)
    if categoria.usuario_id != current_user.id:
        flash('Você não pode excluir esta categoria.', 'danger')
        return redirect(url_for('ver_categorias'))
    Tarefa.query.filter_by(categoria_id=categoria.id).update({'categoria_id': None})
    db.session.delete(categoria)
    db.session.commit()
    flash('Categoria excluída. As tarefas ficaram sem categoria.', 'success')
    return redirect(url_for('ver_categorias'))

# cria rota para gerar arquivo .ics
@app.route('/tarefa/<int:tarefa_id>/exportar_ics')
@login_required
def exportar_ics(tarefa_id):
    tarefa = db.get_or_404(Tarefa, tarefa_id)
    
    if tarefa.prazo:
        inicio = tarefa.prazo.strftime('%Y%m%dT%H%M00')
        fim = (tarefa.prazo + timedelta(hours=1)).strftime('%Y%m%dT%H%M00')
    else:
        inicio = agora_local().strftime('%Y%m%dT%H%M00')
        fim = (agora_local() + timedelta(hours=1)).strftime('%Y%m%dT%H%M00')

    conteudo_ics = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Gerenciador de Tarefas//PT
BEGIN:VEVENT
SUMMARY:{tarefa.titulo}
DESCRIPTION:{tarefa.descricao or ''}
DTSTART:{inicio}
DTEND:{fim}
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR"""

    return Response(
        conteudo_ics,
        mimetype="text/calendar",
        headers={"Content-disposition": f"attachment; filename=tarefa_{tarefa.id}.ics"}
    )

#definir categoria
@app.route('/tarefas/<int:tarefa_id>/categoria', methods=['POST'])
@login_required
def definir_categoria(tarefa_id):
    tarefa = db.get_or_404(Tarefa, tarefa_id)
    if tarefa.criador_id != current_user.id or tarefa.equipe_id:
        flash('Você só pode categorizar as tarefas individuais que você criou.', 'danger')
        return redirect(url_for('quadro'))
    tarefa.categoria_id = categoria_valida(request.form.get('categoria_id'))
    db.session.commit()
    return redirect(request.referrer or url_for('quadro'))

#ver categorias
@app.route('/categorias')
@login_required
def ver_categorias():
    todas = categorias_do_usuario()
    contagem = {c.id: 0 for c in todas}
    sem_categoria = 0
    for t in tarefas_individuais():
        if t.categoria_id in contagem:
            contagem[t.categoria_id] += 1
        else:
            sem_categoria += 1
    compartilhadas = CategoriaCompartilhada.query.filter_by(usuario_id=current_user.id).all()
    return render_template('categorias.html', categorias=todas,
                           contagem=contagem, sem_categoria=sem_categoria,
                           compartilhadas=compartilhadas)

#ver categoria
@app.route('/categorias/<int:categoria_id>')
@login_required
def ver_categoria(categoria_id):
    categoria = db.get_or_404(Categoria, categoria_id)
    if categoria.usuario_id != current_user.id:
        flash('Essa categoria não é sua.', 'danger')
        return redirect(url_for('ver_categorias'))
    todas = tarefas_individuais()
    dentro = [t for t in todas if t.categoria_id == categoria.id]
    disponiveis = [t for t in todas if t.categoria_id != categoria.id]
    ja = {cs.usuario_id for cs in categoria.compartilhamentos}
    meus_contatos = contatos_aceitos()
    convidaveis = [u for u in meus_contatos if u.id not in ja]
    return render_template('categoria.html', categoria=categoria,
                           tarefas=dentro, disponiveis=disponiveis,
                           compartilhamentos=categoria.compartilhamentos,
                           convidaveis=convidaveis,
                           total_contatos=len(meus_contatos))

#adicionar a uma categoria
@app.route('/categorias/<int:categoria_id>/adicionar', methods=['POST'])
@login_required
def adicionar_a_categoria(categoria_id):
    categoria = db.get_or_404(Categoria, categoria_id)
    if categoria.usuario_id != current_user.id:
        flash('Essa categoria não é sua.', 'danger')
        return redirect(url_for('ver_categorias'))
    permitidas = {t.id: t for t in tarefas_individuais()}
    adicionadas = 0
    for tid in request.form.getlist('tarefa_ids', type=int):
        if tid in permitidas:
            permitidas[tid].categoria_id = categoria.id
            adicionadas += 1
    db.session.commit()
    flash(f'{adicionadas} tarefa(s) adicionada(s) à categoria.' if adicionadas else 'Nenhuma tarefa selecionada.',
          'success' if adicionadas else 'info')
    return redirect(url_for('ver_categoria', categoria_id=categoria.id))

#contatos
@app.route('/contatos')
@login_required
def contatos():
    pedidos_enviados = Contato.query.filter_by(
        solicitante_id=current_user.id, status='pendente'
    ).order_by(Contato.criado_em.desc()).all()

    tarefas_enviadas = Tarefa.query.filter(
        Tarefa.criador_id == current_user.id,
        Tarefa.responsavel_id != current_user.id,
        Tarefa.equipe_id.is_(None)
    ).order_by(Tarefa.id.desc()).all()

    pendentes_por_contato = {}
    for t in tarefas_enviadas:
        if t.aceite == 'aguardando':
            pendentes_por_contato[t.responsavel_id] = pendentes_por_contato.get(t.responsavel_id, 0) + 1

    return render_template('contatos.html',
                           contatos=contatos_aceitos(),
                           pedidos_enviados=pedidos_enviados,
                           tarefas_enviadas=tarefas_enviadas,
                           pendentes_por_contato=pendentes_por_contato,
                           limite_tarefas=LIMITE_TAREFAS_PENDENTES_POR_CONTATO)

#adicionar contato
@app.route('/contatos/adicionar', methods=['POST'])
@login_required
def adicionar_contato():
    ident = request.form.get('identificador', '').strip().lstrip('@')
    if not ident:
        flash('Digite o e-mail ou o nome de usuário.', 'danger')
        return redirect(url_for('contatos'))

    alvo = Usuario.query.filter((Usuario.email == ident.lower()) | (Usuario.nomeUsuario == ident)).first()
    if not alvo:
        flash('Nenhum usuário encontrado com esse e-mail ou nome de usuário.', 'danger')
        return redirect(url_for('contatos'))
    if alvo.id == current_user.id:
        flash('Você não pode adicionar a si mesmo.', 'danger')
        return redirect(url_for('contatos'))

    vinculo = buscar_vinculo(current_user.id, alvo.id)
    if vinculo:
        if vinculo.status == 'aceito':
            flash('Vocês já são contatos.', 'info')
        elif vinculo.destinatario_id == current_user.id:
            vinculo.status = 'aceito'
            db.session.commit()
            flash(f'Você e {alvo.nomeUsuario} agora são contatos.', 'success')
        else:
            flash('Você já enviou um pedido para essa pessoa. Aguarde a resposta.', 'info')
        return redirect(url_for('contatos'))

    pendentes = Contato.query.filter_by(solicitante_id=current_user.id, status='pendente').count()
    if pendentes >= LIMITE_PEDIDOS_PENDENTES:
        flash(f'Você já tem {LIMITE_PEDIDOS_PENDENTES} pedidos pendentes. Aguarde respostas ou cancele algum.', 'danger')
        return redirect(url_for('contatos'))

    db.session.add(Contato(solicitante_id=current_user.id, destinatario_id=alvo.id))  # type: ignore
    db.session.commit()
    flash(f'Pedido enviado para {alvo.nomeUsuario}.', 'success')
    return redirect(url_for('contatos'))

#aceitar um contato
@app.route('/contatos/<int:contato_id>/aceitar', methods=['POST'])
@login_required
def aceitar_contato(contato_id):
    c = db.get_or_404(Contato, contato_id)
    if c.destinatario_id != current_user.id or c.status != 'pendente':
        flash('Pedido inválido.', 'danger')
        return redirect(url_for('notificacoes'))
    c.status = 'aceito'
    db.session.commit()
    flash(f'Você e {c.solicitante.nomeUsuario} agora são contatos.', 'success')
    return redirect(url_for('notificacoes'))

#recusar contato
@app.route('/contatos/<int:contato_id>/recusar', methods=['POST'])
@login_required
def recusar_contato(contato_id):
    c = db.get_or_404(Contato, contato_id)
    if c.destinatario_id != current_user.id or c.status != 'pendente':
        flash('Pedido inválido.', 'danger')
        return redirect(url_for('notificacoes'))
    db.session.delete(c)
    db.session.commit()
    flash('Pedido recusado.', 'info')
    return redirect(url_for('notificacoes'))

#cancelar pedido
@app.route('/contatos/<int:contato_id>/cancelar_pedido', methods=['POST'])
@login_required
def cancelar_pedido_contato(contato_id):
    c = db.get_or_404(Contato, contato_id)
    if c.solicitante_id != current_user.id or c.status != 'pendente':
        flash('Pedido inválido.', 'danger')
        return redirect(url_for('contatos'))
    db.session.delete(c)
    db.session.commit()
    flash('Pedido cancelado.', 'info')
    return redirect(url_for('contatos'))

#remover contato
@app.route('/contatos/<int:usuario_id>remover', methods=['POST'])
@login_required
def remover_contato(usuario_id):
    vinculo = buscar_vinculo(current_user.id, usuario_id)
    if not vinculo or vinculo.status != 'aceito':
        flash('Essa pessoa não está nos seus contatos.', 'danger')
        return redirect(url_for('contatos'))
    limpar_vinculos(current_user.id, usuario_id)
    db.session.delete(vinculo)
    db.session.commit()
    flash('Contato removido.', 'success')
    return redirect(url_for('contatos'))

#tarefas entre contatos
@app.route('/contatos/<int:usuario_id>/enviar_tarefa', methods=['POST'])
@login_required
def enviar_tarefa_contato(usuario_id):
    if usuario_id == current_user.id or not sao_contatos(usuario_id):
        flash('Você só pode enviar tarefas para os seus contatos.', 'danger')
        return redirect(url_for('contatos'))

    titulo = request.form.get('titulo', '').strip()
    descricao = request.form.get('descricao', '').strip()
    prioridade = request.form.get('prioridade', 'A definir')
    if not titulo:
        flash('O título da tarefa é obrigatório.', 'danger')
        return redirect(url_for('contatos'))
    if prioridade not in PRIORIDADES_VALIDAS:
        flash('Prioridade inválida.', 'danger')
        return redirect(url_for('contatos'))
    try:
        prazo = validar_prazo((request.form.get('prazo') or '').replace('T', ' '))
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('contatos'))

    pendentes = Tarefa.query.filter_by(
        criador_id=current_user.id, responsavel_id=usuario_id,
        equipe_id=None, aceite='aguardando'
    ).count()
    if pendentes >= LIMITE_TAREFAS_PENDENTES_POR_CONTATO:
        flash(f'Você já tem {LIMITE_TAREFAS_PENDENTES_POR_CONTATO} tarefas aguardando resposta desse contato. '
              'Espere ele responder ou cancele alguma.', 'danger')
        return redirect(url_for('contatos'))

    db.session.add(Tarefa(titulo=titulo, descricao=descricao, status='Pendente', prioridade=prioridade,  # type: ignore
                          prazo=prazo, criador_id=current_user.id, responsavel_id=usuario_id,
                          aceite='aguardando'))
    db.session.commit()
    flash('Tarefa enviada. Ela só vai para o quadro do contato depois que ele aceitar.', 'success')
    return redirect(url_for('contatos'))

#aceitar tarefa
@app.route('/tarefas/<int:tarefa_id>/aceitar', methods=['POST'])
@login_required
def aceitar_tarefa(tarefa_id):
    t = db.get_or_404(Tarefa, tarefa_id)
    if t.responsavel_id != current_user.id or t.aceite != 'aguardando':
        flash('Essa tarefa não está aguardando a sua resposta.', 'danger')
        return redirect(url_for('notificacoes'))
    t.aceite = 'aceita'
    db.session.commit()
    flash('Tarefa aceita! Ela já está no seu quadro.', 'success')
    return redirect(url_for('notificacoes'))

#recusar tarefa
@app.route('/tarefas/<int:tarefa_id>recusar', methods=['POST'])
@login_required
def recusar_tarefa(tarefa_id):
    t = db.get_or_404(Tarefa, tarefa_id)
    if t.responsavel_id != current_user.id or t.aceite != 'aguardando':
        flash('Essa tarefa não está aguardando a sua resposta.', 'danger')
        return redirect(url_for('notificacoes'))
    t.aceite = 'recusada'
    db.session.commit()
    flash('Tarefa recusada.', 'info')
    return redirect(url_for('notificacoes'))

#cancelar envio de tarefa
@app.route('/tarefas/<int:tarefa_id>/cancelar_envio', methods=['POST'])
@login_required
def cancelar_envio_tarefa(tarefa_id):
    destino = proximo_seguro() or url_for('contatos')
    t = db.get_or_404(Tarefa, tarefa_id)
    if t.criador_id != current_user.id or t.equipe_id or t.aceite == 'aceita':
        flash('Só dá para cancelar envios que ainda não foram aceitos.', 'danger')
        return redirect(destino)
    db.session.delete(t)
    db.session.commit()
    flash('Envio cancelado.', 'info')
    return redirect(destino)

#notificacoes
@app.route('/notificacoes')
@login_required
def notificacoes():
    pedidos = Contato.query.filter_by(
        destinatario_id=current_user.id, status='pendente'
    ).order_by(Contato.criado_em.desc()).all()
    convites = ConviteEquipe.query.filter_by(
        convidado_id=current_user.id
    ).order_by(ConviteEquipe.criado_em.desc()).all()
    tarefas = Tarefa.query.filter_by(
        responsavel_id=current_user.id, aceite='aguardando'
    ).order_by(Tarefa.id.desc()).all()
    return render_template('notificacoes.html', pedidos=pedidos, convites=convites, tarefas=tarefas)

#convite para equipe
@app.route('/equipes/<int:equipe_id>/convidar', methods=['POST'])
@login_required
def convidar_contato(equipe_id):
    equipe = db.get_or_404(Equipe, equipe_id)
    if not eh_admin_equipe(equipe):
        flash('Só o criador ou um admin da equipe pode convidar.', 'danger')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))

    usuario_id = request.form.get('usuario_id', type=int)
    if not usuario_id or not sao_contatos(usuario_id):
        flash('Você só pode convidar pessoas que estão nos seus contatos.', 'danger')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))
    if any(m.usuario_id == usuario_id for m in equipe.membros):
        flash('Essa pessoa já é membro da equipe.', 'info')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))
    if ConviteEquipe.query.filter_by(equipe_id=equipe.id, convidado_id=usuario_id).first():
        flash('Essa pessoa já tem um convite pendente.', 'info')
        return redirect(url_for('ver_equipe', equipe_id=equipe.id))

    db.session.add(ConviteEquipe(equipe_id=equipe.id, convidado_id=usuario_id, convidante_id=current_user.id))  # type: ignore
    db.session.commit()
    flash('Convite enviado.', 'success')
    return redirect(url_for('ver_equipe', equipe_id=equipe.id))

#aceitar convite de equipe
@app.route('/convites/<int:convite_id>/aceitar', methods=['POST'])
@login_required
def aceitar_convite(convite_id):
    convite = db.get_or_404(ConviteEquipe, convite_id)
    if convite.convidado_id != current_user.id:
        flash('Convite inválido.', 'danger')
        return redirect(url_for('notificacoes'))
    equipe = convite.equipe
    if not eh_membro(equipe):
        db.session.add(MembroEquipe(equipe_id=equipe.id, usuario_id=current_user.id))  # type: ignore
    db.session.delete(convite)
    db.session.commit()
    flash(f'Você entrou na equipe "{equipe.nome}".', 'success')
    return redirect(url_for('ver_equipe', equipe_id=equipe.id))

#recusar convite
@app.route('/convites/<int:convite_id>/recusar', methods=['POST'])
@login_required
def recusar_convite(convite_id):
    convite = db.get_or_404(ConviteEquipe, convite_id)
    if convite.convidado_id != current_user.id:
        flash('Convite inválido.', 'danger')
        return redirect(url_for('notificacoes'))
    db.session.delete(convite)
    db.session.commit()
    flash('Convite recusado.', 'info')
    return redirect(url_for('notificacoes'))

#cancelar convite
@app.route('/convites/<int:convite_id>/cancelar', methods=['POST'])
@login_required
def cancelar_convite(convite_id):
    convite = db.get_or_404(ConviteEquipe, convite_id)
    equipe_id = convite.equipe_id
    if not eh_admin_equipe(convite.equipe):
        flash('Só o criador ou um admin da equipe pode cancelar convites.', 'danger')
        return redirect(url_for('equipes'))
    db.session.delete(convite)
    db.session.commit()
    flash('Convite cancelado.', 'info')
    return redirect(url_for('ver_equipe', equipe_id=equipe_id))

#compartilhar categoria com um contato
@app.route('/categorias/<int:categoria_id>/compartilhar', methods=['POST'])
@login_required
def compartilhar_categoria(categoria_id):
    categoria = db.get_or_404(Categoria, categoria_id)
    if categoria.usuario_id != current_user.id:
        flash('Essa categoria não é sua.', 'danger')
        return redirect(url_for('ver_categorias'))
    usuario_id = request.form.get('usuario_id', type=int)
    if not usuario_id or not sao_contatos(usuario_id):
        flash('Você só pode compartilhar com os seus contatos.', 'danger')
        return redirect(url_for('ver_categoria', categoria_id=categoria.id))
    if CategoriaCompartilhada.query.filter_by(categoria_id=categoria.id, usuario_id=usuario_id).first():
        flash('Essa categoria já está compartilhada com essa pessoa.', 'info')
        return redirect(url_for('ver_categoria', categoria_id=categoria.id))
    db.session.add(CategoriaCompartilhada(categoria_id=categoria.id, usuario_id=usuario_id))  # type: ignore
    db.session.commit()
    flash('Categoria compartilhada.', 'success')
    return redirect(url_for('ver_categoria', categoria_id=categoria.id))

#descompartilhar categoria
@app.route('/categorias/<int:categoria_id>/descompartilhar/<int:usuario_id>', methods=['POST'])
@login_required
def descompartilhar_categoria(categoria_id, usuario_id):
    categoria = db.get_or_404(Categoria, categoria_id)
    if categoria.usuario_id != current_user.id:
        flash('Essa categoria não é sua.', 'danger')
        return redirect(url_for('ver_categorias'))
    cs = CategoriaCompartilhada.query.filter_by(categoria_id=categoria.id, usuario_id=usuario_id).first_or_404()
    db.session.delete(cs)
    db.session.commit()
    flash('Acesso removido.', 'success')
    return redirect(url_for('ver_categoria', categoria_id=categoria.id))

#ver categoria compartilhada
@app.route('/categorias/compartilhadas/<int:categoria_id>')
@login_required
def ver_categoria_compartilhada(categoria_id):
    categoria = db.get_or_404(Categoria, categoria_id)
    if not categoria_acessivel(categoria):
        flash('Você não tem acesso a essa categoria.', 'danger')
        return redirect(url_for('ver_categorias'))

    tarefas = Tarefa.query.filter(
        Tarefa.categoria_id == categoria.id,
        Tarefa.equipe_id.is_(None)
    ).order_by(Tarefa.id.desc()).all()
    # tarefas recusadas só aparecem para quem as enviou
    tarefas = [t for t in tarefas if t.aceite != 'recusada' or t.criador_id == current_user.id]

    membros = membros_da_categoria(categoria)
    atribuiveis = [u for u in membros if u.id == current_user.id or sao_contatos(u.id)]

    return render_template('categoria_compartilhada.html',
                           categoria=categoria, tarefas=tarefas, membros=membros,
                           atribuiveis=atribuiveis,
                           eh_dono_categoria=categoria.usuario_id == current_user.id,
                           limite_tarefas=LIMITE_TAREFAS_PENDENTES_POR_CONTATO)

@app.route('/categorias/<int:categoria_id>/nova_tarefa', methods=['POST'])
@login_required
def nova_tarefa_categoria(categoria_id):
    categoria = db.get_or_404(Categoria, categoria_id)
    if not categoria_acessivel(categoria):
        flash('Você não tem acesso a essa categoria.', 'danger')
        return redirect(url_for('ver_categorias'))
    destino = url_for('ver_categoria_compartilhada', categoria_id=categoria.id)

    titulo = request.form.get('titulo', '').strip()
    descricao = request.form.get('descricao', '').strip()
    prioridade = request.form.get('prioridade', 'A definir')
    if not titulo:
        flash('O título da tarefa é obrigatório.', 'danger')
        return redirect(destino)
    if prioridade not in PRIORIDADES_VALIDAS:
        flash('Prioridade inválida.', 'danger')
        return redirect(destino)
    try:
        prazo = validar_prazo((request.form.get('prazo') or '').replace('T', ' '))
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(destino)

    responsavel_id = request.form.get('responsavel_id', type=int) or current_user.id
    permitidos = {u.id for u in membros_da_categoria(categoria)
                  if u.id == current_user.id or sao_contatos(u.id)}
    if responsavel_id not in permitidos:
        flash('Escolha um participante da categoria que seja seu contato.', 'danger')
        return redirect(destino)

    if responsavel_id == current_user.id:
        aceite = 'aceita'
    else:
        pendentes = Tarefa.query.filter_by(
            criador_id=current_user.id, responsavel_id=responsavel_id,
            equipe_id=None, aceite='aguardando'
        ).count()
        if pendentes >= LIMITE_TAREFAS_PENDENTES_POR_CONTATO:
            flash(f'Você já tem {LIMITE_TAREFAS_PENDENTES_POR_CONTATO} tarefas aguardando resposta dessa pessoa.', 'danger')
            return redirect(destino)
        aceite = 'aguardando'   # <- troque por 'aceita' se quiser que não precise de aceite aqui

    db.session.add(Tarefa(titulo=titulo, descricao=descricao, status='Pendente', prioridade=prioridade,  # type: ignore
                          prazo=prazo, criador_id=current_user.id, responsavel_id=responsavel_id,
                          categoria_id=categoria.id, aceite=aceite))
    db.session.commit()
    flash('Tarefa criada.' if aceite == 'aceita' else 'Tarefa enviada. Ela só entra no quadro da pessoa depois que ela aceitar.', 'success')
    return redirect(destino)

@app.route('/categorias/<int:categoria_id>/sair', methods=['POST'])
@login_required
def sair_categoria_compartilhada(categoria_id):
    cs = CategoriaCompartilhada.query.filter_by(
        categoria_id=categoria_id, usuario_id=current_user.id
    ).first_or_404()
    db.session.delete(cs)
    db.session.commit()
    flash('Você saiu da categoria.', 'success')
    return redirect(url_for('ver_categorias'))


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        garantir_schema()
    app.run(debug=True)