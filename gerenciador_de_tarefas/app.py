
















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
    return render_template('quadro_admin.html', tarefas = tarefas)
# sujeito a mudanças, feitos sem 'from flask import Flask'