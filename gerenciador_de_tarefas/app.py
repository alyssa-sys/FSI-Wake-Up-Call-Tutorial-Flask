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
    if current_user.cargo != 'admin':
        flash("Acesso negado!", 'danger')
        return redirect(url_for('quadro'))

    tarefas = Tarefa.query.all()
    return render_template('quadro_admin.html', tarefas = tarefas)

#adicionar tarefa
@app.route('/adicionar_tarefa', methods=['GET', 'POST'])
@login_required
def adicionar_tarefa():
    if request.method == 'POST':
        titulo = request.form['titulo']
        descricao = request.form['descricao']
        status = 'Pendente'
        try:
            responsavel_id = int(request.form.get('responsavel_id') or current_user.id)
        except ValueError:
            flash('ID do responsável inválido.', 'danger')
            return redirect(url_for('adicionar_tarefa'))
        if not db.session.get(Usuario, responsavel_id):
            flash('Usuário responsável não encontrado.', 'danger')
            return redirect(url_for('adicionar_tarefa'))

        nova_tarefa = Tarefa(titulo=titulo, descricao=descricao, status=status, criador_id=current_user.id, responsavel_id=responsavel_id) # type: ignore

        db.session.add(nova_tarefa)
        db.session.commit()

        flash('Tarefa adicionada com sucesso!', 'success')
        return redirect(url_for('quadro'))
    
    usuarios = Usuario.query.filter(Usuario.id != current_user.id).all()
    return render_template('adicionar_tarefa.html', usuarios=usuarios)

#editar tarefa
STATUS_VALIDOS = ['Pendente', 'Em andamento', 'Concluída', 'Cancelada']
@app.route('/editar_tarefa/<int:tarefa_id>', methods=['GET', 'POST'])
@login_required
def editar_tarefa(tarefa_id):
    tarefa = db.get_or_404(Tarefa, tarefa_id)
    if current_user.id != tarefa.criador_id and current_user.id != tarefa.responsavel_id:
        flash('Você não tem permissão para editar esta tarefa.', 'danger')
        return redirect(url_for('quadro'))
    if request.method == 'POST':
        status = request.form['status']
        if status not in STATUS_VALIDOS:
            flash('Status inválido.', 'danger')
            return redirect(url_for('editar_tarefa', tarefa_id=tarefa_id))
        
        tarefa.titulo = request.form['titulo']
        tarefa.descricao = request.form['descricao']
        tarefa.status = status

        db.session.commit()
        flash('Tarefa atualizada com sucesso!', 'success')
        return redirect(url_for('quadro'))
    return render_template('editar_tarefa.html', tarefa=tarefa)

#excluir tarefa
@app.route('/excluir_tarefa/<int:tarefa_id>', methods=['POST'])
@login_required
def excluir_tarefa(tarefa_id):
    tarefa = db.get_or_404(Tarefa, tarefa_id)
    if current_user.id != tarefa.criador_id and current_user.id != tarefa.responsavel_id:
        flash('Você não tem permissão para excluir esta tarefa.', 'danger')
        return redirect(url_for('quadro'))
    
    db.session.delete(tarefa)
    db.session.commit()

    flash('Tarefa excluída com sucesso!', 'success')
    return redirect(url_for('quadro'))

#rota do quadro (Dashboard)
@app.route('/quadro')
@login_required
def quadro():
    minhas_tarefas = Tarefa.query.filter_by(criador_id=current_user.id).all()
    tarefas_compartilhadas = Tarefa.query.filter(
        Tarefa.responsavel_id==current_user.id, 
        Tarefa.criador_id!=current_user.id
        ).all()
    return render_template('quadro.html', minhas_tarefas=minhas_tarefas, tarefas_compartilhadas=tarefas_compartilhadas)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)