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
        tg_nick = request.form.get('tg_nick')
        role = request.form.get('role')
        department = request.form.get('department')
        position = request.form.get('position') or ('Teamlead' if role == 'teamlead' else '')
        username = request.form.get('username')
        password = generate_password_hash(request.form.get('password'))

        added_by_id = None
        # 🔹 Если создаём ментора, он должен быть привязан к ТЛ или разработчику
        if role == 'mentor':
            teamlead_id = request.form.get('teamlead_id')
            if teamlead_id:
                added_by_id = int(teamlead_id)
            else:
                added_by_id = current_user.id  # разработчик как создатель

        # 🔍 Проверка уникальности username
        base_username = username
        counter = 1
        while User.query.filter_by(username=username).first():
            username = f"{base_username}_{counter}"
            counter += 1

        new_user = User(
            tg_nick=tg_nick,
            role=role,
            department=department,
            position=position,
            username=username,
            password=password,
            added_by_id=added_by_id,
            onboarding_status='Не розпочато',
            onboarding_step=0,
            onboarding_step_total=0,
            created_at=datetime.utcnow()
        )
        db.session.add(new_user)
        db.session.commit()

        flash(f"Користувач {username} ({role}) успішно створений!", "success")
        return redirect(url_for('main.developer_dashboard'))

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
        mentors = User.query.filter_by(role='mentor', added_by_id=current_user.id, department=current_user.department).all()
        mentor_ids = [mentor.id for mentor in mentors]
        mentor_ids.append(current_user.id)  # додати себе теж

        managers = User.query.filter(
            User.role == 'manager',
            User.added_by_id.in_(mentor_ids),
            User.department == current_user.department
        ).all()

    elif current_user.role == 'mentor':
        managers = User.query.filter_by(
            role='manager',
            added_by_id=current_user.id,
            department=current_user.department
        ).all()

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

    # 🟢 Формуємо список менторів тільки з того ж відділу
    if current_user.role == 'mentor':
        mentors = [current_user]
    elif current_user.role == 'teamlead':
        mentors = User.query.filter(
            User.role.in_(['mentor', 'teamlead']),
            User.department == current_user.department
        ).all()
    else:
        mentors = []

    if request.method == 'POST':
        tg_nick = request.form['tg_nick']
        department = current_user.department  # 🔹 Фіксуємо департамент по ролі, а не з форми
        position = request.form.get('position')
        username = request.form['username']
        password = generate_password_hash(request.form['password'])

        # 🟢 Визначаємо ментора
        mentor_id = request.form.get('mentor_id')
        if not mentor_id:
            mentor_id = current_user.id

        # 🔍 Перевірка унікальності username
        base_username = username
        counter = 1
        while User.query.filter_by(username=username).first():
            username = f"{base_username}_{counter}"
            counter += 1

        # 🟢 Створення менеджера
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

    if current_user.role not in ['mentor', 'teamlead', 'developer']:
        return redirect(url_for('main.login'))

    # 🔹 Шаблони онбордингу (можно оставить без фильтра, они общие)
    templates = OnboardingTemplate.query.all()
    for t in templates:
        try:
            parsed = json.loads(t.structure) if isinstance(t.structure, str) else t.structure
            blocks = parsed.get('blocks') if isinstance(parsed, dict) else parsed
            t.step_count = sum(1 for block in blocks if block.get('type') == 'stage')
        except Exception as e:
            print(f"[plans] Шаблон {t.id}: помилка JSON: {e}")
            t.step_count = 0

    # 🔹 Фільтруємо менеджерів по ролі та відділу
    if current_user.role == 'mentor':
        managers = User.query.filter_by(
            role='manager',
            added_by_id=current_user.id,
            department=current_user.department
        ).all()
    elif current_user.role == 'teamlead':
        mentors = User.query.filter_by(
            role='mentor',
            added_by_id=current_user.id,
            department=current_user.department
        ).all()
        mentor_ids = [mentor.id for mentor in mentors] + [current_user.id]

        managers = User.query.filter(
            User.role == 'manager',
            User.added_by_id.in_(mentor_ids),
            User.department == current_user.department
        ).all()
    elif current_user.role == 'developer':
        managers = User.query.filter_by(role='manager').all()
    else:
        managers = []

    # 🔹 Плани онбордингу
    user_plans_data = []
    for m in managers:
        instance = OnboardingInstance.query.filter_by(manager_id=m.id).first()
        total_steps = 0
        if instance and instance.structure:
            try:
                raw = instance.structure
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                blocks = parsed.get('blocks') if isinstance(parsed, dict) else parsed
                total_steps = len([b for b in blocks if b.get("type") == "stage"])
            except Exception as e:
                print(f"[plans] ❌ manager {m.id} structure error: {e}")

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
        managers = User.query.filter_by(
            role='manager',
            added_by_id=current_user.id,
            department=current_user.department
        ).all()
    elif current_user.role == 'teamlead':
        mentors = User.query.filter_by(
            role='mentor',
            added_by_id=current_user.id,
            department=current_user.department
        ).all()
        mentor_ids = [mentor.id for mentor in mentors] + [current_user.id]
        managers = User.query.filter(
            User.role == 'manager',
            User.added_by_id.in_(mentor_ids),
            User.department == current_user.department
        ).all()
    else:
        managers = []

    return render_template('add_template.html', managers=managers)

@bp.route('/onboarding/template/add', methods=['GET', 'POST'])
@login_required
def add_onboarding_template():
    # 📌 POST — сохранение нового шаблона или онбординга
    if request.method == 'POST':
        raw_structure = request.form.get('structure')
        try:
            structure = json.loads(raw_structure)
        except Exception as e:
            print("❌ Ошибка парсинга structure при POST:", e)
            structure = []

        selected_manager_id = request.form.get('selected_manager')
        name = request.form.get('name')

        payload = {'blocks': structure}  # ← ЕДИНЫЙ формат

        if selected_manager_id == 'template':
            new_template = OnboardingTemplate(
                name=name,
                structure=payload,              # ← БЕЗ json.dumps
                created_by=current_user.id
            )
            db.session.add(new_template)
            db.session.commit()
        else:
            new_instance = OnboardingInstance(
                name=name,
                structure=payload,              # ← БЕЗ json.dumps
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

    # 📌 GET — подготовка данных для формы (оставь как есть, только чтение делаем мягким)
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
        try:
            parsed = template.structure if not isinstance(template.structure, str) else json.loads(template.structure)
            structure = parsed.get('blocks', []) if isinstance(parsed, dict) else parsed
        except Exception as e:
            print("❌ JSON load error при GET:", e)
            structure = []

        if request.args.get('copy') == '1':
            new_template = OnboardingTemplate(
                name=f"{template.name} (копія)",
                structure={'blocks': structure},   # ← объект
                created_by=current_user.id
            )
            db.session.add(new_template)
            db.session.commit()

            return redirect(url_for('main.add_onboarding_template', template_id=new_template.id))

        name = template.name

    return render_template(
        'add_template.html',
        template=template,
        managers=managers,
        structure=structure,
        structure_json=structure,
        name=name,
        selected_manager='template'
    )

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
            parsed = json.loads(new_structure) if isinstance(new_structure, str) else new_structure
            instance.structure = {'blocks': parsed}     # ← объект, без dumps
            db.session.commit()
            flash("Онбординг оновлено", "success")
            return redirect(url_for('main.onboarding_plans'))
        except Exception as e:
            flash(f"❌ Помилка при збереженні: {e}", "danger")

    # GET — мягкий парсинг (оставь как у тебя)
    try:
        raw = instance.structure
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        structure = parsed['blocks'] if isinstance(parsed, dict) and 'blocks' in parsed else parsed
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
        managers=[]
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
    return redirect(url_for('main.edit_onboarding', manager_id=new_user.id))

@bp.route('/onboarding/save', methods=['POST'])
@login_required
def save_onboarding():
    data = request.get_json()
    manager_id = data.get('manager_id')
    blocks = data.get('blocks', [])

    if not blocks:
        return {'message': 'Порожній онбординг'}, 400

    payload = {'blocks': blocks}  # ← единый формат

    if manager_id:
        user = User.query.get(manager_id)
        if not user or user.role != 'manager':
            return {'message': 'Невірний менеджер'}, 400

        instance = OnboardingInstance.query.filter_by(manager_id=manager_id).first()
        if not instance:
            instance = OnboardingInstance(manager_id=manager_id, structure=payload)
            db.session.add(instance)
        else:
            instance.structure = payload
        db.session.commit()

        user.onboarding_name = f"Онбординг від {current_user.username}"
        user.onboarding_status = 'Не розпочато'
        user.onboarding_step = 0
        user.onboarding_step_total = sum(1 for b in blocks if b.get('type') == 'stage')  # ← было 'text'
        user.onboarding_start = datetime.utcnow()
        user.onboarding_end = None
        db.session.commit()
        return {'message': 'Онбординг збережено'}, 200

    else:
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

    try:
        db.session.delete(user)  # 🧼 Каскад сам видалить всі пов’язані записи
        db.session.commit()
        return '', 204
    except Exception as e:
        db.session.rollback()
        return {'message': f'Помилка при видаленні: {str(e)}'}, 500

@bp.route('/manager_dashboard')
@login_required
def manager_dashboard():
    if current_user.role != 'manager':
        return redirect(url_for('main.login'))

    instance = OnboardingInstance.query.filter_by(manager_id=current_user.id).first()
    if not instance:
        return "Онбординг ще не призначено", 404

    # ✅ Парсим структуру (поддержка dict/list)
    try:
        raw = instance.structure
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, str):  # двойной json
            parsed = json.loads(parsed)

        if isinstance(parsed, dict) and 'blocks' in parsed:
            blocks = parsed['blocks']
        elif isinstance(parsed, list):
            blocks = parsed
        else:
            blocks = []
    except Exception as e:
        print(f"[manager_dashboard] ❌ JSON error: {e}")
        blocks = []

    # ✅ Берём только stage-блоки
    stage_blocks = [b for b in blocks if b.get("type") == "stage"]

    # 🛠 Коррекция шага, если вышел за пределы
    current_step = instance.onboarding_step or 0
    if current_step >= len(stage_blocks):
        current_step = len(stage_blocks) - 1 if stage_blocks else 0

    return render_template(
        'manager_dashboard.html',
        blocks=stage_blocks,
        current_step=current_step
    )

@bp.route('/manager_step/<int:step>', methods=['GET', 'POST'])
@login_required
def manager_step(step):
    from flask import jsonify

    if current_user.role != 'manager':
        return redirect(url_for('main.login'))

    instance = OnboardingInstance.query.filter_by(manager_id=current_user.id).first()
    if not instance:
        return redirect(url_for('main.manager_dashboard'))

    # --- Разбор структуры (мягко, с двойным JSON) ---
    try:
        raw = instance.structure
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        blocks = parsed.get('blocks', []) if isinstance(parsed, dict) else parsed
    except Exception as e:
        print(f"[manager_step] ❌ JSON parse error: {e}")
        blocks = []

    stage_blocks = [b for b in blocks if b.get("type") == "stage"]
    total_steps = len(stage_blocks)
    if step >= total_steps:
        return redirect(url_for('main.manager_dashboard'))

    block = stage_blocks[step]

    # --- Прогресс по шагам (мягко) ---
    progress = instance.test_progress or {}
    if not isinstance(progress, dict):
        try:
            progress = json.loads(progress)
        except Exception:
            progress = {}

    step_key = str(step)
    step_progress = progress.get(step_key, {})
    raw_started   = bool(step_progress.get('started', False))
    raw_completed = bool(step_progress.get('completed', False))

    # --- ПОДСТРАХОВКА: если уже ушли дальше, а этот не completed — закрываем его
    if (instance.onboarding_step or 0) > step and not raw_completed:
        prev = progress.get(step_key, {})
        prev['started'] = True
        prev['completed'] = True
        progress[step_key] = prev
        instance.test_progress = progress
        db.session.commit()
        raw_started = True
        raw_completed = True

    # --- Анти-чит: НЕ автозапускаем тест по querystring, UI сам решает, что показывать
    ui_started = raw_started and not raw_completed
    print(f"[manager_step GET] step={step} started={raw_started} completed={raw_completed} ui_started={ui_started}")

    # --- Обработка POST (сабмит ответов теста) ---
    def process_questions(questions, answers_dict):
        correct_count = 0
        total_test_questions = 0
        open_questions_count = 0
        for i, q in enumerate(questions or []):
            q_text = (q.get('question') or '').strip() or "—"
            q_type = q.get('type', 'choice')
            field_name = f"q0_{i}"

            if q_type == 'choice':
                user_input = (answers_dict.getlist(field_name)
                              if q.get('multiple') else answers_dict.get(field_name))
                correct_answers = [a['value'] for a in q.get('answers', []) if a.get('correct')]
                selected = ", ".join(user_input) if isinstance(user_input, list) else (user_input or "")
                is_correct = (set(user_input) == set(correct_answers)) if isinstance(user_input, list) else (selected in correct_answers)
                db.session.add(TestResult(
                    manager_id=current_user.id,
                    onboarding_instance_id=instance.id,
                    step=step,
                    question=q_text,
                    correct_answer=", ".join(correct_answers) if correct_answers else None,
                    selected_answer=selected or None,
                    is_correct=is_correct
                ))
                total_test_questions += 1
                if is_correct:
                    correct_count += 1
            else:
                user_input = answers_dict.get(field_name)
                db.session.add(TestResult(
                    manager_id=current_user.id,
                    onboarding_instance_id=instance.id,
                    step=step,
                    question=q_text,
                    correct_answer=None,
                    selected_answer=user_input or None,
                    is_correct=None
                ))
                open_questions_count += 1
        return correct_count, total_test_questions, open_questions_count

    if request.method == 'POST':
        # если шаг уже завершён — возвращаем «ок» без двойной записи
        if raw_completed:
            return jsonify({'status': 'ok', 'correct': 0, 'total_choice': 0, 'open_questions': 0})

        form = request.form
        correct = total_choice = open_q_count = 0

        if block.get('test') and block['test'].get('questions'):
            c, t, o = process_questions(block['test']['questions'], form)
            correct += c; total_choice += t; open_q_count += o

        for sb in (block.get('subblocks') or []):
            if sb.get('test') and sb['test'].get('questions'):
                c, t, o = process_questions(sb['test']['questions'], form)
                correct += c; total_choice += t; open_q_count += o

        for i, oq in enumerate(block.get('open_questions') or []):
            q_text = (oq.get('question') or '').strip() or "—"
            field_name = f"open_q_{i}"
            user_input = form.get(field_name)
            db.session.add(TestResult(
                manager_id=current_user.id,
                onboarding_instance_id=instance.id,
                step=step,
                question=q_text,
                correct_answer=None,
                selected_answer=user_input or None,
                is_correct=None
            ))
            open_q_count += 1

        # --- Фиксируем завершение шага и двигаем курсор онбординга
        progress[step_key] = {'started': True, 'completed': True}
        instance.test_progress = progress
        instance.onboarding_step = max(instance.onboarding_step or 0, step + 1)
        current_user.onboarding_step = instance.onboarding_step
        db.session.commit()

        print(f"[manager_step POST] COMPLETE step={step} progress[{step_key}]={progress[step_key]}")

        return jsonify({
            'status': 'ok',
            'correct': correct,
            'total_choice': total_choice,
            'open_questions': open_q_count
        })

    # --- Рендер ---
    return render_template(
        'manager_step.html',
        step=step,
        total_steps=total_steps,
        block=block,
        test_started=raw_started,      # отдаём СЫРЫЕ флаги — фронт сам решает, что показывать
        test_completed=raw_completed
    )

@bp.route('/manager_results/<int:manager_id>/<int:onboarding_id>')
@login_required
def manager_results(manager_id, onboarding_id):
    if current_user.role not in ['mentor', 'teamlead', 'developer']:
        return redirect(url_for('main.login'))

    manager = User.query.get_or_404(manager_id)
    instance = OnboardingInstance.query.get_or_404(onboarding_id)

    if manager.role != 'manager' or instance.manager_id != manager.id:
        abort(403)

    # 🔐 Проверка доступа
    if current_user.role == 'mentor':
        if manager.added_by_id != current_user.id:
            abort(403)

    elif current_user.role == 'teamlead':
        if manager.added_by_id != current_user.id:
            mentor = User.query.get(manager.added_by_id)
            if not mentor or mentor.added_by_id != current_user.id:
                abort(403)

    # 🔍 Загружаем только те результаты, что относятся к этому онбордингу
    results = TestResult.query.filter_by(
        manager_id=manager.id,
        onboarding_instance_id=onboarding_id
    ).order_by(TestResult.step.asc()).all()

    choice_results = [r for r in results if r.is_correct is not None]
    open_results = [r for r in results if r.is_correct is None]

    return render_template(
        'manager_results.html',
        manager=manager,
        instance=instance,
        choice_results=choice_results,
        open_results=open_results
    )
    
# --- API: старт теста ---
@bp.route('/api/test/start/<int:step>', methods=['POST'])
@login_required
def api_test_start(step):
    instance = OnboardingInstance.query.filter_by(manager_id=current_user.id).first_or_404()
    progress = instance.test_progress or {}
    if not isinstance(progress, dict):
        try: progress = json.loads(progress)
        except Exception: progress = {}
    prev = progress.get(str(step)) or {}
    prev['started'] = True
    progress[str(step)] = prev
    instance.test_progress = progress
    db.session.commit()
    print(f"[START] step={step} progress={progress}")  # ← лог
    return {'status': 'ok'}


# --- API: завершение теста ---
@bp.route('/api/test/complete/<int:step>', methods=['POST'])
@login_required
def api_test_complete(step):
    instance = OnboardingInstance.query.filter_by(manager_id=current_user.id).first_or_404()
    progress = instance.test_progress or {}

    prev = progress.get(str(step), {})
    prev['started'] = True
    prev['completed'] = True
    progress[str(step)] = prev
    instance.test_progress = progress

    db.session.commit()

    # 🛠️ Лог для проверки
    print(f"[COMPLETE] Step={step}, Progress after update={progress}")

    return {'status': 'ok'}