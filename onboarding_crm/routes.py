from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, abort
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime
from onboarding_crm.models import OnboardingTemplate, OnboardingInstance, OnboardingStep, User, TestResult
from werkzeug.security import check_password_hash, generate_password_hash
from onboarding_crm.extensions import db
from onboarding_crm.utils import parse_nested_structure
import json
import random
import re

bp = Blueprint('main', __name__)
@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_input = request.form.get('login')
        password_input = request.form.get('password')

        user = User.query.filter_by(username=login_input).first()
        if user and check_password_hash(user.password, password_input):
            login_user(user)
            if user.role == 'developer':
                return redirect(url_for('main.developer_dashboard'))
            elif user.role == 'mentor' or user.role == 'teamlead':
                return redirect(url_for('main.mentor_dashboard'))
            elif user.role == 'manager':
                return redirect(url_for('main.manager_dashboard'))
        return "Невірний логін або пароль", 401
    return render_template('login.html')

@bp.route("/")
def index():
    return redirect(url_for('main.login'))  

@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.login'))

@bp.route('/dashboard/developer', methods=['GET', 'POST'])
@login_required
def developer_dashboard():
    if current_user.role != 'developer':
        return redirect(url_for('main.login'))

    if request.method == 'POST':
        tg_nick = request.form['tg_nick']
        role = request.form['role']
        department = request.form['department']
        position = request.form['position']
        username = request.form['username']
        password = generate_password_hash(request.form['password'])

        added_by_id = None
        if role == 'mentor':
            teamlead_id = request.form.get('teamlead_id')
            if teamlead_id:
                added_by_id = int(teamlead_id)

        new_user = User(
            tg_nick=tg_nick,
            role=role,
            department=department,
            position=position,
            username=username,
            password=password,
            added_by_id=added_by_id
        )
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('main.developer_dashboard'))

    # ⬇️ Передаємо список ТЛів у шаблон
    teamleads = User.query.filter_by(role='teamlead').all()
    users = User.query.all()
    return render_template('developer_dashboard.html', users=users, teamleads=teamleads)

@bp.route('/dashboard/mentor')
@login_required
def mentor_dashboard():
    if current_user.role not in ['mentor', 'teamlead']:
        return redirect(url_for('main.login'))
    return render_template('mentor_dashboard.html')

@bp.route('/managers/list')
@login_required
def managers_list():
    if current_user.role not in ['mentor', 'teamlead', 'developer']:
        return redirect(url_for('main.login'))

    if current_user.role == 'developer':
        managers = User.query.filter_by(role='manager').all()

    elif current_user.role == 'teamlead':
        mentors = User.query.filter_by(role='mentor', added_by_id=current_user.id).all()
        mentor_ids = [mentor.id for mentor in mentors]
        print(f"[DEBUG] Mentors added_by TL {current_user.username}: {[m.username for m in mentors]}")
        print(f"[DEBUG] Mentor IDs: {mentor_ids}")

        mentor_ids.append(current_user.id)  # додати себе теж

        managers = User.query.filter(User.role == 'manager', User.added_by_id.in_(mentor_ids)).all()
        print(f"[DEBUG] Found managers: {[m.username for m in managers]}")

    elif current_user.role == 'mentor':
        managers = User.query.filter_by(role='manager', added_by_id=current_user.id).all()
        print(f"[DEBUG] Mentor's own managers: {[m.username for m in managers]}")

    # Підрахунок етапів
    for manager in managers:
        instance = OnboardingInstance.query.filter_by(manager_id=manager.id).first()
        if instance and instance.structure:
            try:
                structure = instance.structure
                if isinstance(structure, str):
                    structure = json.loads(structure)
                if isinstance(structure, str):
                    structure = json.loads(structure)
                blocks = structure.get('blocks') if isinstance(structure, dict) else structure
                total = len([b for b in blocks if b.get("type") == "stage"])
                setattr(manager, 'total_steps_calculated', total)
            except Exception as e:
                print(f"[managers_list] ❌ Error parsing structure for manager {manager.id}: {e}")
                setattr(manager, 'total_steps_calculated', 0)
        else:
            setattr(manager, 'total_steps_calculated', 0)

    return render_template('managers_list.html', managers=managers)

@bp.route('/add_manager', methods=['GET', 'POST'])
@login_required
def add_manager():
    if current_user.role not in ['mentor', 'teamlead']:
        return redirect(url_for('main.login'))

    # 🟢 Формуємо список менторів
    if current_user.role == 'mentor':
        mentors = [current_user]
    elif current_user.role == 'teamlead':
        mentors = User.query.filter(User.role.in_(['mentor', 'teamlead'])).all()
    else:
        mentors = []

    if request.method == 'POST':
        tg_nick = request.form['tg_nick']
        department = request.form['department']
        position = request.form.get('position')
        username = request.form['username']
        password = generate_password_hash(request.form['password'])

        # 🟢 Визначаємо ментора
        mentor_id = request.form.get('mentor_id')
        if not mentor_id:
            mentor_id = current_user.id

        new_user = User(
            tg_nick=tg_nick,
            position=position,
            department=department,
            role='manager',
            username=username,
            password=password,
            added_by_id=int(mentor_id)
        )
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('main.managers_list'))

    return render_template('add_manager.html', mentors=mentors)

@bp.route('/onboarding/plans')
@login_required
def onboarding_plans():
    import json

    if current_user.role not in ['mentor', 'teamlead']:
        return redirect(url_for('main.login'))

    # 🔹 Шаблони онбордингу
    templates = OnboardingTemplate.query.all()
    for t in templates:
        try:
            parsed = json.loads(t.structure) if isinstance(t.structure, str) else t.structure
            if isinstance(parsed, dict) and 'blocks' in parsed:
                blocks = parsed['blocks']
            else:
                blocks = parsed
            t.step_count = sum(1 for block in blocks if block.get('type') == 'stage')
        except Exception as e:
            print(f"[plans] Шаблон {t.id}: помилка JSON: {e}")
            t.step_count = 0

    # 🔹 Менеджери
    if current_user.role == 'mentor':
        managers = User.query.filter_by(role='manager', added_by_id=current_user.id).all()
    elif current_user.role == 'teamlead':
        managers = User.query.filter_by(role='manager').all()
    else:
        managers = []

    # 🔹 Плани онбордингу для кожного менеджера
    user_plans_data = []
    for m in managers:
        instance = OnboardingInstance.query.filter_by(manager_id=m.id).first()

        total_steps = 0
        if instance and instance.structure:
            try:
                raw = instance.structure
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, dict) and 'blocks' in parsed:
                    blocks = parsed['blocks']
                else:
                    blocks = parsed
                total_steps = len([b for b in blocks if b.get("type") == "stage"])
            except Exception as e:
                print(f"[plans] ❌ manager {m.id} structure error: {e}")
                total_steps = 0

        user_plans_data.append({
            'id': m.id,
            'name': f"Онбординг для @{m.tg_nick or m.username}",
            'completed': m.onboarding_step or 0,
            'total': total_steps,
            'mentor': m.added_by.tg_nick if m.added_by else '—'
        })

    return render_template(
        "onboarding_plans.html",
        templates=templates,
        user_plans=user_plans_data
    )  

@bp.route('/onboarding/editor')
@login_required
def onboarding_editor():
    if current_user.role not in ['mentor', 'teamlead']:
        return redirect(url_for('main.login'))

    if current_user.role == 'mentor':
        managers = User.query.filter_by(role='manager', added_by_id=current_user.id).all()
    elif current_user.role == 'teamlead':
        managers = User.query.filter_by(role='manager').all()
    else:
        managers = []

    return render_template('add_template.html', managers=managers)

@bp.route('/onboarding/template/add', methods=['GET', 'POST'])
@login_required
def add_onboarding_template():
    if request.method == 'POST':
        raw_structure = request.form.get('structure')
        structure = json.loads(raw_structure)

        selected_manager_id = request.form.get('selected_manager')
        name = request.form.get('name')

        if selected_manager_id == 'template':
            new_template = OnboardingTemplate(
                name=name,
                structure=json.dumps({'blocks': structure}),
                created_by=current_user.id
            )
            db.session.add(new_template)
            db.session.commit()
        else:
            new_instance = OnboardingInstance(
                name=name,
                structure=json.dumps({'blocks': structure}),
                manager_id=int(selected_manager_id),
                mentor_id=current_user.id
            )
            db.session.add(new_instance)
            db.session.commit()

            manager = User.query.get(int(selected_manager_id))
            manager.onboarding_name = name
            manager.onboarding_status = 'in_progress'
            manager.onboarding_step = 0
            manager.onboarding_step_total = sum(1 for b in structure if b.get('type') == 'stage')
            manager.onboarding_start = datetime.utcnow()
            manager.onboarding_end = None
            db.session.commit()

        return redirect(url_for('main.onboarding_plans'))

    # GET — підготовка форми
    if current_user.role == 'mentor':
        managers = User.query.filter_by(role='manager', added_by_id=current_user.id).all()
    elif current_user.role == 'teamlead':
        managers = User.query.filter_by(role='manager').all()
    else:
        managers = []

    template_id = request.args.get('template_id')
    structure = []
    name = ""
    template = None

    if template_id:
        template = OnboardingTemplate.query.get_or_404(int(template_id))
        name = template.name
        try:
            parsed = json.loads(template.structure)
            structure = parsed.get('blocks', []) if isinstance(parsed, dict) else parsed
        except Exception as e:
            print("❌ JSON load error:", e)
            structure = []

        if request.args.get('copy') == '1':
            name += " (копія)"

    return render_template(
        'add_template.html',
        template=template,
        managers=managers,
        structure=structure,
        structure_json=structure,
        name=name,
        selected_manager='template'
    )

@bp.route('/onboarding/template/edit/<int:template_id>', methods=['GET', 'POST'])
@login_required
def edit_onboarding_template(template_id):
    template = OnboardingTemplate.query.get_or_404(template_id)

    if request.method == 'POST':
        raw_structure = request.form.get('structure')
        structure = json.loads(raw_structure)
        template.name = request.form['name']
        template.structure = json.dumps({'blocks': structure})
        db.session.commit()
        return redirect(url_for('main.onboarding_plans'))

    try:
        parsed = json.loads(template.structure)
        structure_data = parsed.get('blocks', []) if isinstance(parsed, dict) else parsed
    except Exception as e:
        print("❌ JSON error:", e)
        structure_data = []

    return render_template(
        'add_template.html',
        structure=structure_data,
        structure_json=structure_data,
        name=template.name,
        selected_manager='template',
        managers=[],
        template=template
    )


@bp.route('/onboarding/template/copy/<int:template_id>', methods=['GET'])
@login_required
def copy_onboarding_template(template_id):
    """
    Перенаправляє на форму додавання шаблону з уже існуючим template_id,
    але як копія (copy=1), без прямого рендера.
    """
    template = OnboardingTemplate.query.get_or_404(template_id)
    return redirect(url_for('main.add_onboarding_template', template_id=template.id, copy='1'))


@bp.route('/onboarding/user/edit/<int:manager_id>', methods=['GET', 'POST'])
@login_required
def edit_onboarding(manager_id):
    if current_user.role not in ['mentor', 'teamlead']:
        return redirect(url_for('main.login'))

    instance = OnboardingInstance.query.filter_by(manager_id=manager_id).first()
    if not instance:
        flash("Онбординг не знайдено", "danger")
        return redirect(url_for('main.onboarding_plans'))

    user = User.query.get(manager_id)
    onboarding_step = user.onboarding_step or 0

    if request.method == 'POST':
        new_structure = request.form.get('structure')
        try:
            parsed = json.loads(new_structure)
            instance.structure = json.dumps({'blocks': parsed}, ensure_ascii=False)
            db.session.commit()
            flash("Онбординг оновлено", "success")
            return redirect(url_for('main.onboarding_plans'))
        except Exception as e:
            flash(f"❌ Помилка при збереженні: {e}", "danger")

    # 🧠 GET-запит: готуємо структуру
    try:
        raw = instance.structure
        if isinstance(raw, str):
            parsed = json.loads(raw)
        else:
            parsed = raw

        if isinstance(parsed, str):  # подвійний JSON
            parsed = json.loads(parsed)

        if isinstance(parsed, dict) and 'blocks' in parsed:
            structure = parsed['blocks']
        else:
            structure = parsed
    except Exception as e:
        print(f"[edit_onboarding] ❌ JSON parse error: {e}")
        structure = []

    return render_template(
        'add_template.html',
        structure=structure,
        structure_json=json.dumps(structure, ensure_ascii=False),
        name=user.onboarding_name or "",
        selected_manager=manager_id,
        onboarding_step=onboarding_step,
        is_edit=True,
        managers=[]  # ⚠️ не потрібен список менторів
    )

@bp.route('/onboarding/user/copy/<int:id>')
@login_required
def copy_user_onboarding(id):
    original = User.query.get_or_404(id)
    if original.role != 'manager':
        flash('Цей користувач не є менеджером.', 'warning')
        return redirect(url_for('main.onboarding_plans'))

    new_user = User(
        tg_nick=original.tg_nick,
        department=original.department,
        position=original.position,
        username=original.username + '_copy',
        password=original.password,
        role='manager',
        added_by_id=current_user.id,
        onboarding_name=original.onboarding_name + ' (копія)',
        onboarding_status='Не розпочато',
        onboarding_step=0,
        onboarding_step_total=original.onboarding_step_total
    )
    db.session.add(new_user)
    db.session.commit()
    return redirect(url_for('main.edit_user_onboarding', id=new_user.id))

@bp.route('/onboarding/save', methods=['POST'])
@login_required
def save_onboarding():
    data = request.get_json()
    manager_id = data.get('manager_id')
    blocks = data.get('blocks', [])

    if not blocks:
        return {'message': 'Порожній онбординг'}, 400

    if manager_id:
        # Зберігаємо як онбординг для менеджера
        user = User.query.get(manager_id)
        if not user or user.role != 'manager':
            return {'message': 'Невірний менеджер'}, 400

        # 🟢 Створюємо або оновлюємо OnboardingInstance
        instance = OnboardingInstance.query.filter_by(manager_id=manager_id).first()
        if not instance:
            instance = OnboardingInstance(manager_id=manager_id, structure=blocks)
            db.session.add(instance)
        else:
            instance.structure = blocks
        db.session.commit()

        user.onboarding_name = f"Онбординг від {current_user.username}"
        user.onboarding_status = 'Не розпочато'
        user.onboarding_step = 0
        user.onboarding_step_total = len([b for b in blocks if b['type'] == 'text'])
        user.onboarding_start = datetime.utcnow()
        user.onboarding_end = None
        db.session.commit()
        return {'message': 'Онбординг збережено'}, 200

    else:
        # Зберігаємо як шаблон
        template = OnboardingTemplate(
            name=f"Шаблон від {current_user.username}",
            created_at=datetime.utcnow()
        )
        db.session.add(template)
        db.session.flush()

        order = 1
        for b in blocks:
            step = OnboardingStep(
                template_id=template.id,
                title=b['title'],
                description=b['content'],
                order=order,
                step_type=b['type']
            )
            db.session.add(step)
            order += 1

        db.session.commit()
        return {'message': 'Шаблон збережено'}, 200

@bp.route('/onboarding/template/delete/<int:id>', methods=['DELETE'])
@login_required
def delete_onboarding_template(id):
    template = OnboardingTemplate.query.get_or_404(id)
    # Видаляємо всі кроки, пов’язані з шаблоном
    OnboardingStep.query.filter_by(template_id=template.id).delete()
    db.session.delete(template)
    db.session.commit()
    return '', 204

@bp.route('/onboarding/user/delete/<int:id>', methods=['DELETE'])
@login_required
def delete_user_onboarding(id):
    user = User.query.get_or_404(id)

    # 🧱 Заборона для mentor-ів
    if current_user.role == 'mentor':
        return {'message': 'У вас немає прав на видалення'}, 403

    # 🔐 Якщо Teamlead — може видаляти лише менеджерів
    if current_user.role == 'teamlead' and user.role != 'manager':
        return {'message': 'Тімлід може видаляти лише менеджерів'}, 403

    # 🧹 Видаляємо всі пов'язані онбординги
    instances = OnboardingInstance.query.filter_by(manager_id=user.id).all()
    for instance in instances:
        db.session.delete(instance)

    # ❌ Сам користувач
    db.session.delete(user)
    db.session.commit()
    return '', 204

@bp.route('/manager_dashboard')
@login_required
def manager_dashboard():
    if current_user.role != 'manager':
        return redirect(url_for('main.login'))

    instance = OnboardingInstance.query.filter_by(manager_id=current_user.id).first()
    if not instance:
        return "Онбординг ще не призначено", 404

    # ✅ Парсимо структуру
    try:
        raw = instance.structure
        if isinstance(raw, str):
            parsed = json.loads(raw)
        else:
            parsed = raw

        if isinstance(parsed, str):  # подвійний json
            parsed = json.loads(parsed)

        blocks = parsed.get('blocks', [])
    except Exception as e:
        print(f"[manager_dashboard] JSON error: {e}")
        blocks = []

    # ✅ Збираємо тільки stage-блоки
    stage_blocks = [b for b in blocks if b.get("type") == "stage"]
    current_step = instance.onboarding_step or 0

    return render_template(
        'manager_dashboard.html',
        blocks=stage_blocks,
        current_step=current_step
    )

@bp.route('/manager_step/<int:step>', methods=['GET', 'POST'])
@login_required
def manager_step(step):
    import json
    import re
    from flask import jsonify
    from onboarding_crm.models import TestResult, User  # 🟢 Додано User

    if current_user.role != 'manager':
        return redirect(url_for('main.login'))

    instance = OnboardingInstance.query.filter_by(manager_id=current_user.id).first()
    if not instance:
        return redirect(url_for('main.manager_dashboard'))

    # ✅ Парсимо structure
    try:
        raw = instance.structure

        if isinstance(raw, str):
            parsed = json.loads(raw)
        else:
            parsed = raw

        if isinstance(parsed, str):
            parsed = json.loads(parsed)

        if isinstance(parsed, dict) and 'blocks' in parsed:
            blocks = parsed['blocks']
        elif isinstance(parsed, list):
            blocks = parsed
        else:
            raise ValueError("Unsupported structure format")

    except Exception as e:
        print(f"[manager_step] ❌ JSON parse error: {e}")
        blocks = []

    # 🔢 Отримуємо лише stage-блоки
    stage_blocks = [b for b in blocks if b.get("type") == "stage"]
    total_steps = len(stage_blocks)

    if step >= total_steps:
        return redirect(url_for('main.manager_dashboard'))

    block = stage_blocks[step]

    # ✅ Обробка тестів
    def process_questions(questions, answers_dict):
        correct_count = 0
        for q in questions:
            q_text = q['question']
            normalized = re.sub(r'\W+', '_', q_text.strip().lower())
            field_name = f"q0_{normalized}"
            user_input = answers_dict.getlist(field_name) if q.get('multiple') else answers_dict.get(field_name)
            correct_answers = [a['value'] for a in q['answers'] if a.get('correct')]

            if isinstance(user_input, list):
                selected = ", ".join(user_input)
                is_correct = set(user_input) == set(correct_answers)
            else:
                selected = user_input or ""
                is_correct = selected in correct_answers

            if is_correct:
                correct_count += 1

            # ✅ Зберігаємо результат
            tr = TestResult(
                manager_id=current_user.id,
                step=step,
                question=q_text,
                correct_answer=", ".join(correct_answers),
                selected_answer=selected,
                is_correct=is_correct
            )

            print("🧠 Question:", q_text)
            print("➡️ User input:", user_input)
            print("✅ Correct values:", correct_answers)
            print("🎯 Is correct:", is_correct)

            db.session.add(tr)

        return correct_count

    # ✅ POST: обробка тесту
    if request.method == 'POST':
        form_data = request.form
        correct = 0
        total = 0

        # Блоковий тест
        if 'test' in block and 'questions' in block['test']:
            correct += process_questions(block['test']['questions'], form_data)
            total += len(block['test']['questions'])

        # Сабблокові тести
        if 'subblocks' in block:
            for sb in block['subblocks']:
                if 'test' in sb and 'questions' in sb['test']:
                    correct += process_questions(sb['test']['questions'], form_data)
                    total += len(sb['test']['questions'])

        # 🟢 Оновлюємо обидва джерела прогресу
        instance.onboarding_step = step + 1
        user = User.query.get(current_user.id)
        user.onboarding_step = step + 1
        db.session.commit()

        return jsonify({
            'status': 'ok',
            'correct': correct,
            'total': total
        })

    # ✅ GET: показ блоку
    return render_template(
        'manager_step.html',
        step=step,
        total_steps=total_steps,
        block=block
    )

@bp.route('/manager_results/<int:manager_id>')
@login_required
def manager_results(manager_id):
    if current_user.role not in ['mentor', 'teamlead', 'developer']:
        return redirect(url_for('main.login'))

    manager = User.query.get_or_404(manager_id)

    if manager.role != 'manager':
        abort(403)

    # 🔐 Проверка доступа
    if current_user.role == 'mentor':
        # Ментор видит только своих менеджеров
        if manager.added_by_id != current_user.id:
            abort(403)

    elif current_user.role == 'teamlead':
        # 1️⃣ Если ТЛ сам добавил менеджера
        if manager.added_by_id == current_user.id:
            pass
        else:
            # 2️⃣ Если менеджера добавил ментор команды ТЛ
            mentor = User.query.get(manager.added_by_id)
            if not mentor or mentor.added_by_id != current_user.id:
                abort(403)

    # developer видит всех
    results = TestResult.query.filter_by(manager_id=manager.id).order_by(TestResult.step.asc()).all()

    return render_template('manager_results.html', manager=manager, results=results)

@bp.route('/autosave_template/<int:template_id>', methods=['POST'])
@login_required
def autosave_template(template_id):
    template = OnboardingTemplate.query.get_or_404(template_id)
    data = request.get_json()

    if not data or 'structure' not in data:
        return jsonify({'error': 'Invalid data'}), 400

    try:
        template.structure = json.dumps({'blocks': data['structure']})
        db.session.commit()
        return jsonify({'status': 'ok'})
    except Exception as e:
        print("❌ Error saving autosave:", e)
        return jsonify({'error': str(e)}), 500   