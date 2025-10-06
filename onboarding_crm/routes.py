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

# --- Helper: allowed managers for current user (department-aware)
def _allowed_managers_for_current_user():
    """
    Returns a SQLAlchemy query for managers the current user is allowed to see/select.
    - mentor   -> managers with same department and added_by_id = current_user.id
    - teamlead -> managers with same department and added_by_id in [teamlead.id] + mentors created by teamlead in same department
    - developer -> all managers (fallback for tooling/admin)
    - others  -> empty query
    """
    if not current_user.is_authenticated:
        return User.query.filter(False)

    if current_user.role == 'mentor':
        return User.query.filter_by(
            role='manager',
            added_by_id=current_user.id,
            department=current_user.department
        )

    if current_user.role == 'teamlead':
        mentors = User.query.filter_by(
            role='mentor',
            added_by_id=current_user.id,
            department=current_user.department
        ).all()
        mentor_ids = [m.id for m in mentors] + [current_user.id]
        return User.query.filter(
            User.role == 'manager',
            User.added_by_id.in_(mentor_ids),
            User.department == current_user.department
        )

    if current_user.role == 'developer':
        return User.query.filter_by(role='manager')

    return User.query.filter(False)

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

    # --- Додавання нового користувача ---
    if request.method == 'POST':
        tg_nick = request.form.get('tg_nick')
        role = request.form.get('role')
        department = request.form.get('department')
        position = request.form.get('position')
        username = request.form.get('username')
        password = generate_password_hash(request.form.get('password'))
        added_by_id = None

        # Прив'язка до ТЛ, якщо ментор
        if role == 'mentor':
            added_by_id = request.form.get('teamlead_id')
        elif role == 'manager':
            added_by_id = current_user.id  # developer або потім через dropdown

        # 🔁 Унікальний логін, якщо такий вже існує
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
            added_by_id=int(added_by_id) if added_by_id else None
        )
        db.session.add(new_user)
        db.session.commit()
        flash("Користувача додано", "success")
        return redirect(url_for('main.developer_dashboard'))

    # --- Дані для GET ---
    users = User.query.order_by(User.id.desc()).all()
    teamleads = User.query.filter_by(role='teamlead').all()

    return render_template(
        'developer_dashboard.html',
        users=users,
        teamleads=teamleads
    )

@bp.route('/dashboard/mentor')
@login_required
def mentor_dashboard():
    if current_user.role not in ['mentor', 'teamlead', 'head']:
        return redirect(url_for('main.login'))

    # 1. Отримуємо список менеджерів
    if current_user.role == 'mentor':
        managers = User.query.filter_by(
            role='manager',
            added_by_id=current_user.id
        ).all()

    elif current_user.role == 'teamlead':
        mentors = User.query.filter_by(
            role='mentor',
            added_by_id=current_user.id,
            department=current_user.department
        ).all()
        mentor_ids = [m.id for m in mentors] + [current_user.id]
        managers = User.query.filter(
            User.role == 'manager',
            User.added_by_id.in_(mentor_ids),
            User.department == current_user.department
        ).all()

    elif current_user.role == 'head':
        managers = User.query.filter_by(
            role='manager',
            department=current_user.department
        ).all()

    else:
        managers = []

    manager_ids = [m.id for m in managers]

    # 2. Активні онбординги — просто всі, де є структура
    active_onboardings = OnboardingInstance.query.filter(
        OnboardingInstance.manager_id.in_(manager_ids)
    ).count()

    # 3. Середній прогрес
    progresses = [
        m.onboarding_step or 0
        for m in managers if m.onboarding_step is not None
    ]
    average_progress = round(sum(progresses) / len(progresses), 1) if progresses else 0

    return render_template(
        'mentor_dashboard.html',
        managers=managers,
        active_onboardings=active_onboardings,
        average_progress=average_progress
    )
    
@bp.route('/managers/list')
@login_required
def managers_list():
    if current_user.role not in ['mentor', 'teamlead', 'developer', 'head']:
        return redirect(url_for('main.login'))

    if current_user.role == 'developer':
        managers = User.query.filter_by(role='manager').all()

    elif current_user.role == 'teamlead':
        mentors = User.query.filter_by(role='mentor', added_by_id=current_user.id, department=current_user.department).all()
        mentor_ids = [mentor.id for mentor in mentors]
        mentor_ids.append(current_user.id)

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

    elif current_user.role == 'head':
        managers = User.query.filter_by(
            role='manager',
            department=current_user.department
        ).all()    

    # Підрахунок етапів (берём последний инстанс по id)
    for manager in managers:
        instance = (OnboardingInstance.query
                    .filter_by(manager_id=manager.id)
                    .order_by(OnboardingInstance.id.desc())
                    .first())
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

@bp.route('/manager/statistics')
@login_required
def manager_statistics():
    if current_user.role != 'manager':
        return redirect(url_for('main.login'))

    instance = (OnboardingInstance.query
                .filter_by(manager_id=current_user.id)
                .order_by(OnboardingInstance.id.desc())
                .first())

    if not instance:
        print("[DEBUG] ❌ No OnboardingInstance found")
        return render_template('manager_statistics.html', stats=None, final_status=None)

    # Парсимо структуру
    structure_raw = instance.structure
    if isinstance(structure_raw, str):
        try:
            structure = json.loads(structure_raw)
        except Exception as e:
            print(f"[ERROR] ❌ JSON parse error in instance.structure: {e}")
            return render_template('manager_statistics.html', stats=None, final_status=None)
    elif isinstance(structure_raw, (dict, list)):
        structure = structure_raw
    else:
        print("[ERROR] ❌ Unknown format of structure field")
        return render_template('manager_statistics.html', stats=None, final_status=None)

    # Витягуємо результати
    results = TestResult.query.filter_by(onboarding_instance_id=instance.id).all()
    print(f"[DEBUG] ✅ Found {len(results)} TestResult entries")

    # Групуємо по кроках
    results_by_step = {}
    for r in results:
        if r.step not in results_by_step:
            results_by_step[r.step] = []
        results_by_step[r.step].append(r)

    stats = []

    for idx, block in enumerate(structure):
        if block.get('type') != 'stage':
            continue

        step_results = results_by_step.get(idx, [])
        if not step_results:
            print(f"[DEBUG] ℹ️ No results for block index {idx}")
            continue

        # Рахуємо правильні та відкриті
        correct_answers = sum(1 for r in step_results if r.is_correct is True)
        total_questions = sum(1 for r in step_results if r.is_correct is not None)

        block_stats = {
            "title": block.get('title', f"Етап {idx+1}"),
            "correct_answers": correct_answers,
            "total_questions": total_questions,
            "open_questions": []
        }

        for r in step_results:
            if r.is_correct is None:  # відкриті питання
                block_stats["open_questions"].append({
                    "question": r.question,
                    "answer": r.selected_answer,
                    "reviewed": getattr(r, 'reviewed', False),
                    "accepted": getattr(r, 'accepted', None),
                    "feedback": getattr(r, 'feedback', None)
                })

        stats.append(block_stats)

    # Фінальний статус
    if not stats:
        final_status = None
    elif any(oq for step in stats for oq in step["open_questions"] if oq.get("reviewed") is False):
        final_status = 'waiting'
    elif any(oq for step in stats for oq in step["open_questions"] if oq.get("accepted") is False):
        final_status = 'extra_block_added'
    else:
        final_status = 'passed'

    print(f"[DEBUG] ✅ Final status: {final_status}")
    print(f"[DEBUG] ✅ Rendered {len(stats)} blocks")

    return render_template('manager_statistics.html', stats=stats, final_status=final_status)

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
    if current_user.role not in ['mentor', 'teamlead', 'developer', 'head']:
        return redirect(url_for('main.login'))

    templates = OnboardingTemplate.query.all()
    for t in templates:
        try:
            parsed = json.loads(t.structure) if isinstance(t.structure, str) else t.structure
            blocks = parsed.get('blocks') if isinstance(parsed, dict) else parsed
            t.step_count = sum(1 for block in blocks if block.get('type') == 'stage')
        except Exception as e:
            print(f"[plans] Шаблон {t.id}: помилка JSON: {e}")
            t.step_count = 0

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

    user_plans_data = []
    for m in managers:
        instance = (OnboardingInstance.query
                    .filter_by(manager_id=m.id)
                    .order_by(OnboardingInstance.id.desc())
                    .first())
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
            'manager_id': m.id,
            'onboarding_id': instance.id if instance else None,
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

    managers = _allowed_managers_for_current_user().all()
    return render_template('add_template.html', managers=managers)

@bp.route('/onboarding/template/add', methods=['GET', 'POST'])
@login_required
def add_onboarding_template():
    """
    Создание/редактирование шаблона ИЛИ назначение/редактирование онбординга менеджеру.
    Правки:
    - Если находимся по URL с ?template_id=... и выбран "Зберегти як шаблон",
      то делаем UPDATE существующего шаблона вместо создания копии.
    - Если выбран конкретный менеджер: апдейтим его последний OnboardingInstance
      (если он есть), а не создаём новый. Прогресс пользователя не сбрасываем.
    """
    # 📌 POST — сохранение нового или обновление существующего
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

        # Validate chosen manager is allowed for current user (department-aware)
        if selected_manager_id and selected_manager_id != 'template':
            try:
                _target_mid = int(selected_manager_id)
            except Exception:
                _target_mid = None
            if _target_mid is None or _target_mid not in [u.id for u in _allowed_managers_for_current_user().all()]:
                flash("Ви не можете призначити онбординг цьому менеджеру (обмеження по відділу/ролі).", "danger")
                return redirect(url_for('main.onboarding_plans'))

        # Если редактируем существующий шаблон (по query ?template_id=...)
        existing_template_id = request.args.get('template_id')

        if selected_manager_id == 'template':
            # UPDATE существующего шаблона, если пришли с template_id
            if existing_template_id:
                tpl = OnboardingTemplate.query.get(int(existing_template_id))
                if tpl:
                    tpl.name = name
                    tpl.structure = payload
                    db.session.commit()
                    return redirect(url_for('main.onboarding_plans'))
            # Иначе создаём новый шаблон
            new_template = OnboardingTemplate(
                name=name,
                structure=payload,
                created_by=current_user.id
            )
            db.session.add(new_template)
            db.session.commit()
            return redirect(url_for('main.onboarding_plans'))

        # ---- Ветка: выбран конкретный менеджер ----
        try:
            manager_id_int = int(selected_manager_id)
        except Exception:
            flash("Невірний менеджер", "danger")
            return redirect(url_for('main.onboarding_plans'))

        # Последний инстанс для менеджера
        instance = (OnboardingInstance.query
                    .filter_by(manager_id=manager_id_int)
                    .order_by(OnboardingInstance.id.desc())
                    .first())

        # Если инстанс существует — ОБНОВЛЯЕМ его (не создаём копию)
        if instance:
            instance.name = name
            instance.structure = payload
            db.session.commit()
        else:
            # Иначе создаём новый и инициализируем поля пользователя
            new_instance = OnboardingInstance(
                name=name,
                structure=payload,
                manager_id=manager_id_int,
                mentor_id=current_user.id
            )
            db.session.add(new_instance)
            db.session.commit()

            manager = User.query.get(manager_id_int)
            manager.onboarding_name = name
            manager.onboarding_status = 'in_progress'
            manager.onboarding_step = 0
            manager.onboarding_step_total = sum(1 for b in structure if b.get('type') == 'stage')
            manager.onboarding_start = datetime.utcnow()
            manager.onboarding_end = None
            db.session.commit()

        return redirect(url_for('main.onboarding_plans'))

    # 📌 GET — подготовка данных для формы
    managers = _allowed_managers_for_current_user().all()

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
                structure={'blocks': structure},
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

    # Берём самый свежий інстанс онбординга для менеджера
    instance = (OnboardingInstance.query
                .filter_by(manager_id=manager_id)
                .order_by(OnboardingInstance.id.desc())
                .first())
    if not instance:
        flash("Онбординг не знайдено", "danger")
        return redirect(url_for('main.onboarding_plans'))

    user = User.query.get(manager_id)
    onboarding_step = user.onboarding_step or 0  # курсор следующего к прохождению кроку

    # --- Текущая структура (аккуратный парсинг)
    try:
        raw = instance.structure
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        current_blocks = parsed['blocks'] if isinstance(parsed, dict) and 'blocks' in parsed else parsed
    except Exception as e:
        print(f"[edit_onboarding] ❌ JSON parse error: {e}")
        current_blocks = []

    # --- Индексы stage-блоков (для надёжного сравнения по индексам)
    current_stage_indices = [i for i, b in enumerate(current_blocks) if b.get("type") == "stage"]

    # --- Прогресс по шагам (нормализуем к dict)
    progress = instance.test_progress or {}
    if not isinstance(progress, dict):
        try:
            progress = json.loads(progress)
        except Exception:
            progress = {}

    # --- Формируем множество залоченных индексов:
    #     1) все, где completed == True,
    #     2) все индексы строго меньше onboarding_step (логически завершённые)
    locked_indices = set()
    for i in current_stage_indices:
        p = progress.get(str(i), {}) if isinstance(progress, dict) else {}
        if bool(p.get('completed', False)):
            locked_indices.add(i)
        if i < onboarding_step:
            locked_indices.add(i)

    def _normalize_for_compare(obj):
        try:
            return json.dumps(obj, ensure_ascii=False, sort_keys=True)
        except Exception:
            return str(obj)

    if request.method == 'POST':
        new_structure_raw = request.form.get('structure')
        try:
            new_blocks = json.loads(new_structure_raw) if isinstance(new_structure_raw, str) else new_structure_raw
            # поддерживаем оба формата: либо массив блоков, либо {"blocks":[...]}
            if isinstance(new_blocks, dict) and 'blocks' in new_blocks:
                new_blocks = new_blocks['blocks']
        except Exception as e:
            flash(f"❌ Помилка парсингу нової структури: {e}", "danger")
            return redirect(url_for('main.edit_onboarding', manager_id=manager_id))

        # --- СЕРВЕРНАЯ ВАЛИДАЦИЯ: запрещаем менять / удалять / сдвигать залоченные шаги
        for idx in sorted(list(locked_indices)):
            # 1) Новый массив должен содержать элемент на этом индексе
            if idx >= len(new_blocks):
                flash("Неможливо видалити або зсунути вже пройдені кроки.", "danger")
                return redirect(url_for('main.edit_onboarding', manager_id=manager_id))

            # 2) Тип блока на этом индексе должен быть stage и оставаться stage
            old_is_stage = (current_blocks[idx].get("type") == "stage")
            new_is_stage = (new_blocks[idx].get("type") == "stage")
            if not old_is_stage or not new_is_stage:
                flash("Неможливо змінювати тип або позицію вже пройденого кроку.", "danger")
                return redirect(url_for('main.edit_onboarding', manager_id=manager_id))

            # 3) Содержимое пройденного шага не должно измениться
            before = _normalize_for_compare(current_blocks[idx])
            after  = _normalize_for_compare(new_blocks[idx])
            if before != after:
                flash("Зміни в уже пройдених кроках заборонені. Відкотіть правки в цих кроках.", "danger")
                return redirect(url_for('main.edit_onboarding', manager_id=manager_id))

        # Если валидация прошла — сохраняем новую структуру целиком
        instance.structure = {'blocks': new_blocks}
        db.session.commit()
        flash("Онбординг оновлено", "success")
        return redirect(url_for('main.onboarding_plans'))

    # --- GET: отдаём текущую структуру и список залоченных индексов (чтобы UI мог підсвітити)
    return render_template(
        'add_template.html',
        structure=current_blocks,
        structure_json=json.dumps(current_blocks, ensure_ascii=False),
        name=user.onboarding_name or "",
        selected_manager=manager_id,
        onboarding_step=onboarding_step,
        is_edit=True,
        managers=[],
        locked_indices=sorted(list(locked_indices)),
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

    # Department-aware permission check for mentor/teamlead
    if manager_id and current_user.role in ['mentor', 'teamlead']:
        try:
            _mid = int(manager_id)
        except Exception:
            _mid = None
        if _mid is None or _mid not in [u.id for u in _allowed_managers_for_current_user().all()]:
            return {'message': 'Немає прав призначати онбординг цьому менеджеру'}, 403

    if not blocks:
        return {'message': 'Порожній онбординг'}, 400

    payload = {'blocks': blocks}

    if manager_id:
        user = User.query.get(manager_id)
        if not user or user.role != 'manager':
            return {'message': 'Невірний менеджер'}, 400

        instance = (OnboardingInstance.query
                    .filter_by(manager_id=manager_id)
                    .order_by(OnboardingInstance.id.desc())
                    .first())
        if not instance:
            instance = OnboardingInstance(manager_id=manager_id, structure=payload)
            db.session.add(instance)
        else:
            instance.structure = payload
        db.session.commit()

        user.onboarding_name = f"Онбординг від {current_user.username}"
        user.onboarding_status = 'Не розпочато'
        user.onboarding_step = 0
        user.onboarding_step_total = sum(1 for b in blocks if b.get('type') == 'stage')
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
    
@bp.route('/onboarding/instance/delete/<int:onboarding_id>', methods=['DELETE'])
@login_required
def delete_onboarding_instance(onboarding_id):
    instance = OnboardingInstance.query.get_or_404(onboarding_id)

    print(f"[DELETE] Текущий юзер: {current_user.id}, роль: {current_user.role}")
    print(f"[DELETE] Удаляем онбординг #{onboarding_id}, manager_id: {instance.manager_id}, mentor_id: {instance.mentor_id}")

    manager = User.query.get(instance.manager_id)

    # 🔐 Проверка доступа
    if current_user.role == 'mentor':
        if manager.added_by_id != current_user.id:
            return {'message': 'У вас немає прав на видалення цього онбордингу'}, 403

    elif current_user.role == 'teamlead':
        # Найти всех менторов текущего ТЛ
        mentors = User.query.filter_by(
            role='mentor',
            added_by_id=current_user.id,
            department=current_user.department
        ).all()
        mentor_ids = [m.id for m in mentors] + [current_user.id]

        if manager.added_by_id not in mentor_ids:
            return {'message': 'У вас немає прав на видалення цього онбордингу'}, 403

    elif current_user.role != 'developer':
        return {'message': 'Роль не має прав на видалення онбордингу'}, 403

    try:
        TestResult.query.filter_by(onboarding_instance_id=onboarding_id).delete()
        db.session.delete(instance)
        db.session.commit()
        return '', 204

    except Exception as e:
        db.session.rollback()
        print(f"[DELETE] ❌ Ошибка: {e}")
        return {'message': f'Помилка при видаленні онбордингу: {str(e)}'}, 500

@bp.route('/manager_dashboard')
@login_required
def manager_dashboard():
    if current_user.role != 'manager':
        return redirect(url_for('main.login'))

    # Берём самый свежий инстанс онбординга
    instance = (OnboardingInstance.query
                .filter_by(manager_id=current_user.id)
                .order_by(OnboardingInstance.id.desc())
                .first())
    if not instance:
        return "Онбординг ще не призначено", 404

    print(f"[manager_dashboard] use onboarding_instance id={instance.id}")

    # --- Разбор структуры (мягко, с двойным JSON) ---
    try:
        raw = instance.structure
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, str):
            parsed = json.loads(parsed)

        if isinstance(parsed, dict) and 'blocks' in parsed:
            blocks_all = parsed['blocks']
        elif isinstance(parsed, list):
            blocks_all = parsed
        else:
            blocks_all = []
    except Exception as e:
        print(f"[manager_dashboard] ❌ JSON error: {e}")
        blocks_all = []

    # Берём только stage-блоки
    stage_blocks = [b for b in blocks_all if b.get("type") == "stage"]

    # Текущий курсор онбординга
    current_step = instance.onboarding_step or 0
    if current_step >= len(stage_blocks):
        current_step = len(stage_blocks) - 1 if stage_blocks else 0

    # --- Прогресс по шагам (нормализуем к dict)
    progress = instance.test_progress or {}
    if not isinstance(progress, dict):
        try:
            progress = json.loads(progress)
        except Exception:
            progress = {}

    # --- Строим метаданные по шагам и сразу готовые URL
    steps_meta = []
    for i, b in enumerate(stage_blocks):
        p = progress.get(str(i), {}) if isinstance(progress, dict) else {}
        started = bool(p.get('started', False))
        completed = bool(p.get('completed', False))

        # Если шаг начат и не завершён — добавляем ?start=1,
        # чтобы при возврате сразу открылись тесты (как на шаге 0)
        step_url = url_for('main.manager_step', step=i, start=1) if (started and not completed) \
                   else url_for('main.manager_step', step=i)

        steps_meta.append({
            "index": i,
            "title": b.get("title") or f"Крок {i+1}",
            "description": b.get("description") or "",
            "started": started,
            "completed": completed,
            "url": step_url,
        })

    return render_template(
        'manager_dashboard.html',
        # передаём и «сырой» список блоков, и подготовленные шаги
        blocks=stage_blocks,
        steps_meta=steps_meta,
        current_step=current_step,
    )

@bp.route('/manager_step/<int:step>', methods=['GET', 'POST'])
@login_required
def manager_step(step):
    from flask import jsonify, make_response

    if current_user.role != 'manager':
        return redirect(url_for('main.login'))

    # Берём самый свежий инстанс
    instance = (OnboardingInstance.query
                .filter_by(manager_id=current_user.id)
                .order_by(OnboardingInstance.id.desc())
                .first())
    if not instance:
        return redirect(url_for('main.manager_dashboard'))
    print(f"[manager_step] use onboarding_instance id={instance.id}")

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

    # --- ПОДСТРАХОВКА 1: если уже ушли дальше, а этот не completed — закрываем его
    if (instance.onboarding_step or 0) > step and not raw_completed:
        prev = progress.get(step_key, {})
        prev['started'] = True
        prev['completed'] = True
        progress[step_key] = prev
        instance.test_progress = progress
        db.session.commit()
        raw_started = True
        raw_completed = True

    # --- Fallback по cookie: если браузер пометил шаг как начатый, а в БД ещё нет
    cookie_started = request.cookies.get(f"step_started_{step}") == "1"
    if cookie_started and (not raw_started) and (not raw_completed):
        prev = progress.get(step_key, {})
        prev['started'] = True
        progress[step_key] = prev
        instance.test_progress = progress
        db.session.commit()
        raw_started = True

    # --- Анти-чит: тест начат в БД, но в URL нет start=1 → редиректим на тот же шаг с start=1
    if raw_started and not raw_completed and request.args.get('start') != '1':
        return redirect(url_for('main.manager_step', step=step, start=1), code=302)

    # --- ПОДСТРАХОВКА 2: явный сигнал из URL (?start=1) — пометить step как "started" (completed не трогаем)
    force_start = request.args.get('start') == '1'
    if force_start and (not raw_completed) and (not raw_started):
        prev = progress.get(step_key, {})
        prev['started'] = True
        progress[step_key] = prev
        instance.test_progress = progress
        db.session.commit()
        raw_started = True

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
        # если шаг уже завершён — не дублируем запись
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

        # --- Завершаем шаг и двигаем курсор вперёд
        progress[step_key] = {'started': True, 'completed': True}
        instance.test_progress = progress
        instance.onboarding_step = max(instance.onboarding_step or 0, step + 1)
        current_user.onboarding_step = instance.onboarding_step
        db.session.commit()

        print(f"[manager_step POST] instance_id={instance.id} COMPLETE step={step} progress[{step_key}]={progress[step_key]}")

        return jsonify({
            'status': 'ok',
            'correct': correct,
            'total_choice': total_choice,
            'open_questions': open_q_count
        })

    # --- Рендер с анти-кэш заголовками и синхронизацией cookie ---
    html = render_template(
        'manager_step.html',
        step=step,
        total_steps=total_steps,
        block=block,
        test_started=raw_started,
        test_completed=raw_completed
    )
    resp = make_response(html)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'

    # Состояние cookie ↔ состояние БД:
    #  - если started и не completed → cookie=1
    #  - иначе → удаляем cookie
    if raw_started and not raw_completed:
        resp.set_cookie(f"step_started_{step}", "1", path=f"/manager_step/{step}", samesite="Lax")
    else:
        resp.delete_cookie(f"step_started_{step}", path=f"/manager_step/{step}")

    return resp

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
    # Берём самый свежий инстанс, как и в остальных местах
    instance = (OnboardingInstance.query
                .filter_by(manager_id=current_user.id)
                .order_by(OnboardingInstance.id.desc())
                .first_or_404())

    progress = instance.test_progress or {}
    if not isinstance(progress, dict):
        try:
            progress = json.loads(progress)
        except Exception:
            progress = {}

    key = str(step)
    prev = progress.get(key, {})
    # только помечаем started, completed не трогаем
    prev['started'] = True
    progress[key] = prev

    instance.test_progress = progress
    db.session.commit()

    print(f"[START] instance_id={instance.id} step={step} progress={progress}")

    # Возвращаем JSON и одновременно ставим cookie, чтобы «анти-чит» переживал Back/Fwd
    resp = jsonify({'status': 'ok'})
    # cookie действует на страницу шага; живёт до конца сессии
    resp.set_cookie(f"step_started_{step}", "1", path=f"/manager_step/{step}", samesite="Lax")
    return resp


# --- API: завершение теста ---
@bp.route('/api/test/complete/<int:step>', methods=['POST'])
@login_required
def api_test_complete(step):
    instance = (OnboardingInstance.query
                .filter_by(manager_id=current_user.id)
                .order_by(OnboardingInstance.id.desc())
                .first_or_404())

    progress = instance.test_progress or {}
    if not isinstance(progress, dict):
        try:
            progress = json.loads(progress)
        except Exception:
            progress = {}

    key = str(step)
    prev = progress.get(key, {})
    prev['completed'] = True
    prev['started']  = prev.get('started', True)  # если не было start → считаем, что был
    progress[key] = prev

    instance.test_progress = progress

    # если этот шаг был текущим, продвигаем дальше
    if instance.onboarding_step is None or instance.onboarding_step <= step:
        instance.onboarding_step = step + 1

    db.session.commit()
    print(f"[COMPLETE] instance_id={instance.id} step={step} progress={progress}")

    # Чистим cookie «старт шага», чтобы при возврате не открывался тест
    resp = jsonify({'status': 'ok'})
    resp.delete_cookie(f"step_started_{step}", path=f"/manager_step/{step}")
    return resp