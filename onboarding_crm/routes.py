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

    # 2. Активні інстанси онбордингу (не в архіві)
    active_instances = OnboardingInstance.query.filter(
        OnboardingInstance.manager_id.in_(manager_ids),
        OnboardingInstance.archived == False
    ).all()

    # 3. Архівовані інстанси
    archived_count = OnboardingInstance.query.filter(
        OnboardingInstance.manager_id.in_(manager_ids),
        OnboardingInstance.archived == True
    ).count()

    # 4. Прогрес по кожному інстансу
    progress_list = []
    for i in active_instances:
        structure = i.structure or []
        total = len(structure)
        completed = min(i.onboarding_step or 0, total)

        if total > 0:
            percent = round((completed / total) * 100, 1)
            progress_list.append(percent)

    average_progress = round(sum(progress_list) / len(progress_list), 1) if progress_list else 0

    return render_template(
        'mentor_dashboard.html',
        managers=managers,
        active_onboardings=len(active_instances),
        archived_count=archived_count,
        average_progress=average_progress
    )
    
@bp.route('/managers/list')
@login_required
def managers_list():
    if current_user.role not in ['mentor', 'teamlead', 'developer', 'head']:
        return redirect(url_for('main.login'))

    # 🔹 1. Базовая выборка менеджеров по ролям
    if current_user.role == 'developer':
        managers = User.query.filter_by(role='manager').all()

    elif current_user.role == 'teamlead':
        mentors = User.query.filter_by(
            role='mentor',
            added_by_id=current_user.id,
            department=current_user.department
        ).all()
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

    # 🔹 2. Формирование финального списка
    filtered_managers = []
    for manager in managers:
        # Получаем последний онбординг-инстанс
        instance = (OnboardingInstance.query
                    .filter_by(manager_id=manager.id)
                    .order_by(OnboardingInstance.id.desc())
                    .first())

        # Сохраняем даже если None (для шаблона)
        manager.latest_instance = instance

        # Если онбординг существует, но в архиве — пропускаем
        if instance and instance.archived:
            continue

        # Подсчёт количества этапов (если структура есть)
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
            # Если онбординга ещё нет — ставим 0 этапов
            setattr(manager, 'total_steps_calculated', 0)

        # Добавляем менеджера в финальный список
        filtered_managers.append(manager)

    managers = filtered_managers

    # 🔹 3. Рендер страницы
    return render_template('managers_list.html', managers=managers)

@bp.route('/manager/statistics')
@login_required
def manager_statistics():
    if current_user.role != 'manager':
        return redirect(url_for('main.login'))

    # 🔹 Отримуємо останній інстанс онбордингу
    instance = (OnboardingInstance.query
                .filter_by(manager_id=current_user.id)
                .order_by(OnboardingInstance.id.desc())
                .first())

    if not instance:
        print("[DEBUG] ❌ No OnboardingInstance found")
        return render_template('manager_statistics.html', stats=None, final_status=None)

    # 🔹 Парсимо структуру
    structure_raw = instance.structure
    if isinstance(structure_raw, str):
        try:
            structure = json.loads(structure_raw)
        except Exception as e:
            print(f"[ERROR] ❌ JSON parse error: {e}")
            return render_template('manager_statistics.html', stats=None, final_status=None)
    elif isinstance(structure_raw, (dict, list)):
        structure = structure_raw
    else:
        print("[ERROR] ❌ Unknown format for structure")
        return render_template('manager_statistics.html', stats=None, final_status=None)

    # 🔹 Нормалізуємо структуру
    if isinstance(structure, dict) and 'blocks' in structure:
        structure = structure['blocks']

    if not isinstance(structure, list):
        print("[ERROR] ❌ Structure is not a list")
        return render_template('manager_statistics.html', stats=None, final_status=None)

    # 🔹 Отримуємо результати
    results = TestResult.query.filter_by(onboarding_instance_id=instance.id).all()
    print(f"[DEBUG] ✅ Found {len(results)} TestResult entries")

    results_by_step = {}
    for r in results:
        results_by_step.setdefault(r.step, []).append(r)

    stats = []
    for idx, block in enumerate(structure):
        if not isinstance(block, dict):
            print(f"[ERROR] ❌ Block {idx} is not dict")
            continue

        if block.get('type') != 'stage':
            continue

        step_results = results_by_step.get(idx, [])
        if not step_results:
            continue

        correct_answers = sum(1 for r in step_results if r.is_correct is True)
        total_questions = sum(1 for r in step_results if r.is_correct is not None)

        block_stats = {
            "title": block.get('title', f"Етап {idx+1}"),
            "correct_answers": correct_answers,
            "total_questions": total_questions,
            "open_questions": []
        }

        for r in step_results:
            if r.is_correct is None:
                block_stats["open_questions"].append({
                    "question": r.question,
                    "answer": r.selected_answer,
                    "approved": r.approved,
                    "feedback": r.feedback
                })

        stats.append(block_stats)

    # 🔹 Підрахунок завершених етапів (оновлена логіка)
    total_stage_blocks = sum(1 for b in structure if isinstance(b, dict) and b.get("type") == "stage")

    test_progress = instance.test_progress or {}
    if not isinstance(test_progress, dict):
        try:
            test_progress = json.loads(test_progress)
        except Exception:
            test_progress = {}

    completed_steps = sum(1 for v in test_progress.values()
                          if isinstance(v, dict) and v.get("completed"))
    onboarding_finished = completed_steps >= total_stage_blocks

    print(f"[DEBUG] 📊 Total stages: {total_stage_blocks}, Completed steps: {completed_steps}, Finished={onboarding_finished}")

    # 🔹 Визначаємо фінальний статус
    if not onboarding_finished:
        final_status = None  # Ще проходить етапи
    elif not instance.final_decision:
        final_status = "waiting"  # Очікує фінального рішення
    else:
        # Використовуємо готове фінальне рішення (passed / rejected / extra)
        final_status = instance.final_decision

    print(f"[DEBUG] ✅ Final status (based on final_decision): {final_status}")

    return render_template(
        'manager_statistics.html',
        stats=stats,
        final_status=final_status
    )
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

    # ✅ Templates visibility: developer sees all, others only within their department
    templates_q = OnboardingTemplate.query
    if current_user.role != 'developer':
        # Prefer direct department column on template; fallback to creator's department if available
        if hasattr(OnboardingTemplate, 'department'):
            templates_q = templates_q.filter(OnboardingTemplate.department == current_user.department)
        elif hasattr(OnboardingTemplate, 'created_by'):
            templates_q = templates_q.join(User, OnboardingTemplate.created_by == User.id) \
                                   .filter(User.department == current_user.department)

    templates = templates_q.all()
    for t in templates:
        try:
            parsed = json.loads(t.structure) if isinstance(t.structure, str) else t.structure
            if isinstance(parsed, str):
                parsed = json.loads(parsed)

            blocks = parsed.get('blocks') if isinstance(parsed, dict) else parsed
            blocks = blocks or []
            t.step_count = sum(
                1 for block in blocks
                if isinstance(block, dict) and block.get('type') == 'stage'
            )
        except Exception as e:
            print(f"[plans] Шаблон {t.id}: помилка JSON: {e}")
            t.step_count = 0

    # ✅ Managers list (department-aware)
    if current_user.role in ['mentor', 'teamlead']:
        managers = _allowed_managers_for_current_user().all()
    elif current_user.role == 'head':
        managers = User.query.filter_by(role='manager', department=current_user.department).all()
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
        completed_steps = 0

        if instance:
            completed_steps = instance.onboarding_step or 0

        if instance and instance.structure:
            try:
                raw = instance.structure
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if isinstance(parsed, str):
                    parsed = json.loads(parsed)

                blocks = parsed.get('blocks') if isinstance(parsed, dict) else parsed
                blocks = blocks or []
                total_steps = sum(
                    1 for b in blocks
                    if isinstance(b, dict) and b.get('type') == 'stage'
                )
            except Exception as e:
                print(f"[plans] ❌ manager {m.id} structure error: {e}")

        user_plans_data.append({
            'manager_id': m.id,
            'onboarding_id': instance.id if instance else None,
            'name': f"Онбординг для @{m.tg_nick or m.username}",
            'completed': completed_steps,
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
    - ✅ Templates now saved with department to avoid cross-department visibility.
    """
    # 📌 POST — сохранение нового или обновление существующего
    if request.method == 'POST':
        raw_structure = request.form.get('structure')
        try:
            structure = json.loads(raw_structure)
        except Exception as e:
            print("❌ Ошибка парсинга structure при POST:", e)
            structure = []

        selected_manager_id = request.form.get('selected_manager') or 'template'
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
                    # ✅ FIX: если департамент пустой — проставляем текущий
                    if not getattr(tpl, 'department', None):
                        tpl.department = current_user.department
                    db.session.commit()
                    return redirect(url_for('main.onboarding_plans'))

            # Иначе создаём новый шаблон
            new_template = OnboardingTemplate(
                name=name,
                structure=payload,
                created_by=current_user.id,
                # ✅ FIX: всегда сохраняем department
                department=current_user.department
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
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            structure = parsed.get('blocks', []) if isinstance(parsed, dict) else parsed
        except Exception as e:
            print("❌ JSON load error при GET:", e)
            structure = []

        if request.args.get('copy') == '1':
            new_template = OnboardingTemplate(
                name=f"{template.name} (копія)",
                structure={'blocks': structure},
                created_by=current_user.id,
                # ✅ FIX: копируем department из оригинала
                department=template.department
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

    # 1. Последний онбординг-инстанс менеджера
    instance = (OnboardingInstance.query
                .filter_by(manager_id=current_user.id)
                .order_by(OnboardingInstance.id.desc())
                .first())
    if not instance:
        return "Онбординг ще не призначено", 404

    print(f"[manager_dashboard] use onboarding_instance id={instance.id}")

    # 2. Разбор структуры
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

    # 3. Выбираем только stage-блоки
    stage_blocks = [b for b in blocks_all if b.get("type") == "stage"]

    # 4. Поточный шаг
    current_step = instance.onboarding_step or 0
    if current_step >= len(stage_blocks):
        current_step = len(stage_blocks) - 1 if stage_blocks else 0

    # 5. Прогресс (dict)
    progress = instance.test_progress or {}
    if not isinstance(progress, dict):
        try:
            progress = json.loads(progress)
        except Exception:
            progress = {}

    # Добавляем progress['0'] при первом запуске
    if '0' not in progress and stage_blocks:
        progress['0'] = {"started": False, "completed": False}
        instance.test_progress = progress
        db.session.commit()

    # 6. Генерация метаданных шагов
    steps_meta = []
    for i, b in enumerate(stage_blocks):
        p = progress.get(str(i), {})
        started = bool(p.get('started', False))
        completed = bool(p.get('completed', False))
        step_url = url_for('main.manager_step', step=i)
        steps_meta.append({
            "index": i,
            "title": b.get("title") or f"Крок {i + 1}",
            "description": b.get("description") or "",
            "started": started,
            "completed": completed,
            "url": step_url,
        })

    # 7. Доступность шагов через onboarding_step
    for i, meta in enumerate(steps_meta):
        meta["accessible"] = (i <= current_step)

    return render_template(
        'manager_dashboard.html',
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

    instance = (OnboardingInstance.query
                .filter_by(manager_id=current_user.id)
                .order_by(OnboardingInstance.id.desc())
                .first())
    if not instance:
        return redirect(url_for('main.manager_dashboard'))

    print(f"[manager_step] use onboarding_instance id={instance.id}")

    # --- Разбор структуры ---
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

    # --- Прогресс ---
    progress = instance.test_progress or {}
    if not isinstance(progress, dict):
        try:
            progress = json.loads(progress)
        except Exception:
            progress = {}

    step_key = str(step)
    step_progress = progress.get(step_key, {})
    raw_started = bool(step_progress.get('started', False))
    raw_completed = bool(step_progress.get('completed', False))

    # --- Подстраховка: если уже прошли дальше, а этот не завершён
    if (instance.onboarding_step or 0) > step and not raw_completed:
        prev = progress.get(step_key, {})
        prev['started'] = True
        prev['completed'] = True
        progress[step_key] = prev
        instance.test_progress = progress
        db.session.commit()
        raw_started = True
        raw_completed = True

    # --- Cookie fallback
    cookie_started = request.cookies.get(f"step_started_{step}") == "1"
    if cookie_started and (not raw_started) and (not raw_completed):
        prev = progress.get(step_key, {})
        prev['started'] = True
        progress[step_key] = prev
        instance.test_progress = progress
        db.session.commit()
        raw_started = True

    # ❌ Удаляем автопереход на ?start=1 (чтобы не пропускать инфо-блок)
    # if raw_started and not raw_completed and request.args.get('start') != '1':
    #     return redirect(url_for('main.manager_step', step=step, start=1), code=302)

    # --- Явный старт по параметру
    force_start = request.args.get('start') == '1'
    if force_start and (not raw_completed):
        prev = progress.get(step_key, {})
        prev['started'] = True
        progress[step_key] = prev
        instance.test_progress = progress
        db.session.commit()
        raw_started = True

    ui_started = raw_started and not raw_completed
    print(f"[manager_step GET] step={step} started={raw_started} completed={raw_completed} ui_started={ui_started}")

    # --- Обработка POST (тест)
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

        # --- Завершаем шаг и открываем следующий
        progress[step_key] = {'started': True, 'completed': True}

        next_step = step + 1
        if next_step < total_steps and str(next_step) not in progress:
            progress[str(next_step)] = {"started": False, "completed": False}

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

    if raw_started and not raw_completed:
        resp.set_cookie(f"step_started_{step}", "1", path=f"/manager_step/{step}", samesite="Lax")
    else:
        resp.delete_cookie(f"step_started_{step}", path=f"/manager_step/{step}")

    return resp

from sqlalchemy import and_

@bp.route('/manager_results/<int:manager_id>/<int:onboarding_id>')
@login_required
def manager_results(manager_id, onboarding_id):
    print("🔒 current_user:", current_user)
    print("🔒 is_authenticated:", current_user.is_authenticated)
    print("🔒 current_user.role:", getattr(current_user, 'role', None))

    if current_user.role not in ['mentor', 'teamlead', 'developer']:
        flash("⛔️ Доступ заборонено", "danger")
        return redirect(url_for('main.managers_list'))

    manager = User.query.get(manager_id)
    instance = OnboardingInstance.query.get(onboarding_id)

    if not manager or not instance:
        flash("❌ Менеджер або онбординг не знайдено", "danger")
        return redirect(url_for('main.managers_list'))

    if instance.manager_id != manager.id:
        flash("⛔️ Онбординг не належить цьому менеджеру", "danger")
        return redirect(url_for('main.managers_list'))

    try:
        structure = json.loads(instance.structure) if isinstance(instance.structure, str) else instance.structure
    except Exception as e:
        print("❌ JSON parsing error:", e)
        flash("❌ Помилка структури онбордингу", "danger")
        return redirect(url_for('main.managers_list'))

    # --- Тестові питання (вибіркові) ---
    choice_results = TestResult.query.filter(
        and_(
            TestResult.manager_id == manager.id,
            TestResult.onboarding_instance_id == instance.id,
            TestResult.is_correct != None
        )
    ).order_by(TestResult.step.asc()).all()

    # --- Відкриті питання ---
    open_results = TestResult.query.filter(
        and_(
            TestResult.manager_id == manager.id,
            TestResult.onboarding_instance_id == instance.id,
            TestResult.is_correct == None
        )
    ).order_by(TestResult.step.asc()).all()

    print(f"📋 Відкритих питань: {len(open_results)}")
    for r in open_results:
        print(f"🧪 Step={r.step} | Approved={r.approved} | Draft={r.draft}")

    # --- Попап логіка ---
    test_progress = instance.test_progress or {}
    completed_blocks = [k for k, v in test_progress.items() if v.get("completed")]
    total_blocks = len(structure or [])

    all_blocks_completed = len(completed_blocks) >= total_blocks
    all_open_checked = all(r.approved is not None and not r.draft for r in open_results)

    show_popup = all_blocks_completed and (not open_results or all_open_checked)

    print(f"📊 Blocks completed: {len(completed_blocks)}/{total_blocks}")
    print(f"📊 Popup: {show_popup}")

    return render_template(
        'manager_results.html',
        manager=manager,
        instance=instance,
        choice_results=choice_results,
        open_results=open_results,
        step=instance.onboarding_step,
        show_popup=show_popup
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

@bp.route('/update_result/<int:result_id>', methods=['POST'])
@login_required
def update_result(result_id):
    """Автоматичне збереження фідбеку (чернетки) для відкритих питань."""
    result = TestResult.query.get_or_404(result_id)

    # 🔐 Перевірка доступу
    if current_user.role not in ['mentor', 'teamlead', 'developer', 'head']:
        return jsonify({'error': 'Access denied'}), 403

    data = request.get_json()
    try:
        if 'approved' in data:
            if data['approved'] == "True":
                result.approved = True
            elif data['approved'] == "False":
                result.approved = False
            else:
                result.approved = None  # якщо не вибрано

        result.feedback = data.get('feedback', '').strip()
        result.draft = True  # 🔸 автосейв завжди як чернетка

        db.session.commit()
        return jsonify({'status': 'success'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    
@bp.route('/publish_feedback/<int:manager_id>', methods=['POST'])
@login_required
def publish_feedback(manager_id):
    """Публікація фідбеку по ВСІМ відкритим питанням менеджера"""
    if current_user.role not in ['mentor', 'teamlead', 'developer', 'head']:
        return jsonify({'error': 'Access denied'}), 403

    try:
        print(f"\n🟦 Publish request for manager_id={manager_id}")

        # Отримуємо ВСІ відкриті відповіді цього менеджера, які ще не опубліковані
        results = TestResult.query.filter(
            TestResult.manager_id == manager_id,
            TestResult.correct_answer == None,        # open question (без правильної відповіді)
            TestResult.selected_answer != None,       # є відповідь менеджера
            TestResult.feedback != None,              # фідбек заповнений
            TestResult.approved != None,              # є оцінка (зараховано / не зараховано)
            TestResult.draft == True                  # ще не опубліковано
        ).all()

        print(f"🔎 Found {len(results)} open results to publish")

        updated = False
        for r in results:
            print(f"🔄 Before update: result_id={r.id}, draft={r.draft}, approved={r.approved}, feedback={r.feedback}")
            r.draft = False  # робимо видимим для менеджера
            db.session.add(r)
            updated = True
            print(f"✅ After update: result_id={r.id}, draft={r.draft}")

        db.session.commit()

        if updated:
            print("✅ Feedback successfully published.")
            flash('Фідбек успішно опубліковано', 'success')
            return jsonify({'status': 'published'}), 200
        else:
            print("ℹ️ Немає нових відповідей для оновлення (усе вже опубліковано або порожньо).")
            return jsonify({'status': 'no_changes'}), 200

    except Exception as e:
        db.session.rollback()
        print(f"❌ Error during publish_feedback: {e}")
        return jsonify({'error': str(e)}), 500
    
@bp.route('/final_feedback/<int:manager_id>')
@login_required
def final_feedback(manager_id):
    """Фінальний фідбек після перевірки всіх етапів онбордингу"""
    # --- Перевірка ролі
    if current_user.role not in ['mentor', 'teamlead', 'developer', 'head']:
        flash("⛔️ Доступ заборонено", "danger")
        return redirect(url_for('main.login'))

    # --- Отримуємо останній інстанс онбордингу
    instance = (OnboardingInstance.query
                .filter_by(manager_id=manager_id)
                .order_by(OnboardingInstance.id.desc())
                .first())

    if not instance:
        flash("❌ Онбординг не знайдено", "danger")
        return redirect(url_for('main.managers_list'))

    # --- Парсимо структуру (бо може бути str)
    structure = instance.structure or []
    if isinstance(structure, str):
        try:
            structure = json.loads(structure)
        except Exception as e:
            print(f"[final_feedback] JSON parse error: {e}")
            structure = []

    # --- Отримуємо результати тестів
    results = TestResult.query.filter_by(onboarding_instance_id=instance.id).all()
    test_results = [r for r in results if r.is_correct is not None]
    open_questions = [r for r in results if r.is_correct is None]

    # ==========================================================
    # 🔹 Розрахунок по тестах
    # ==========================================================
    block_test_stats = {}
    for r in test_results:
        block = r.step or 0
        if block not in block_test_stats:
            block_test_stats[block] = {'total': 0, 'correct': 0}
        block_test_stats[block]['total'] += 1
        if r.is_correct:
            block_test_stats[block]['correct'] += 1

    block_titles = []
    if isinstance(structure, dict) and 'blocks' in structure:
        block_titles = [b.get('title') for b in structure['blocks']]
    elif isinstance(structure, list):
        block_titles = [b.get('title') for b in structure if isinstance(b, dict)]

    weak_test_blocks = []
    for i, stats in block_test_stats.items():
        percent = round((stats['correct'] / stats['total']) * 100, 1)
        if percent < 60:
            title = block_titles[i] if i < len(block_titles) else f"Блок {i+1}"
            weak_test_blocks.append({
                "index": i,
                "title": title,
                "percent": percent
            })

    # якщо всі блоки > 60% — додати найслабший
    if not weak_test_blocks and block_test_stats:
        i, stats = min(block_test_stats.items(), key=lambda x: (x[1]['correct'] / x[1]['total']))
        percent = round((stats['correct'] / stats['total']) * 100, 1)
        title = block_titles[i] if i < len(block_titles) else f"Блок {i+1}"
        weak_test_blocks.append({
            "index": i,
            "title": title,
            "percent": percent
        })

    # ==========================================================
    # 🔹 Розрахунок по відкритих питаннях
    # ==========================================================
    block_open_stats = {}
    for r in open_questions:
        block = r.step or 0
        if block not in block_open_stats:
            block_open_stats[block] = {'total': 0, 'not_approved': 0}
        block_open_stats[block]['total'] += 1
        if r.approved is False:
            block_open_stats[block]['not_approved'] += 1

    weak_open_blocks = []
    for i, s in block_open_stats.items():
        if s['not_approved'] > 2:
            title = block_titles[i] if i < len(block_titles) else f"Блок {i+1}"
            weak_open_blocks.append(title)

    # ==========================================================
    # 🔹 Побудова пояснень по слабких блоках
    # ==========================================================
    explanations = []
    for b in weak_test_blocks:
        explanations.append(f"📉 {b['title']}: низький % по тестах ({b['percent']}%)")

    for title in weak_open_blocks:
        explanations.append(f"🟥 {title}: незараховані відкриті питання")

    # ==========================================================
    # 🔹 Загальний середній відсоток (тестові + відкриті)
    # ==========================================================
    test_percents = [
        (s['correct'] / s['total']) * 100
        for s in block_test_stats.values() if s['total'] > 0
    ]
    open_percents = [
        100 - (s['not_approved'] / s['total']) * 100
        for s in block_open_stats.values() if s['total'] > 0
    ]

    all_percents = test_percents + open_percents
    average_percent = sum(all_percents) / len(all_percents) if all_percents else 100

    # ==========================================================
    # 🔹 Фінальний висновок
    # ==========================================================
    if average_percent >= 71:
        final_recommendation = "✅ Пройдено"
    elif 41 <= average_percent < 71:
        final_recommendation = "🟠 Потребує доопрацювання"
    else:
        final_recommendation = "❌ Не пройдено"

    print(f"[final_feedback] manager={manager_id}, avg={average_percent:.1f}%, weak={len(explanations)}")

    # ==========================================================
    # 🔹 Додаткові обчислення для шаблону
    # ==========================================================
    open_approved_count = len([r for r in open_questions if r.approved is True])
    not_approved_open = len([r for r in open_questions if r.approved is False])
    correct_test_answers = sum(1 for r in test_results if r.is_correct)
    total_test_questions = len(test_results)

    # ==========================================================
    # 🔹 Рендер шаблону
    # ==========================================================
    return render_template(
        'final_feedback.html',
        manager=User.query.get(manager_id),
        instance=instance,
        test_results=test_results,
        open_questions=open_questions,

        # Середній % за тестами та відкритими питаннями
        test_percent=round(sum(test_percents)/len(test_percents)) if test_percents else 100,
        open_percent=round(sum(open_percents)/len(open_percents)) if open_percents else 100,

        # Фінальні рекомендації
        test_recommendation=final_recommendation,
        open_recommendation=final_recommendation,
        final_recommendation=final_recommendation,

        # Пояснення/слабкі блоки
        explanations=explanations,
        summary_issues=explanations,

        # Остаточна оцінка
        average_percent=round(average_percent),
        final_score=round(average_percent),

        # Підрахунки для статистики
        open_approved_count=open_approved_count,
        correct_test_answers=correct_test_answers,
        total_test_questions=total_test_questions,
        not_approved_open=not_approved_open,   # 👈 ВОТ ЭТА СТРОКА


        # Слабкі блоки з назвами
        weak_test_blocks=weak_test_blocks,
        weak_open_blocks=weak_open_blocks,

        # Найслабший блок
        weakest_test_block=weak_test_blocks[0] if weak_test_blocks else None
    )

@bp.route('/final_decision', methods=['POST'])
@login_required
def final_decision():
    instance_id = request.form.get('instance_id')
    decision = request.form.get('decision')
    comment = request.form.get('comment', '')  # опціональний фідбек

    instance = OnboardingInstance.query.get(instance_id)

    if not instance:
        flash("Онбординг не знайдено", "danger")
        return redirect(url_for('main.managers_list'))

    # Збереження фінального рішення
    instance.final_decision = decision
    instance.final_comment = comment

    # ✅ Пройшов
    if decision == 'approved':
        instance.onboarding_status = 'completed'
        instance.archived = True
        flash("✅ Онбординг зараховано", "success")

    # ❌ Не пройшов
    elif decision == 'rejected':
        instance.onboarding_status = 'failed'
        instance.archived = True
        flash("❌ Онбординг не зараховано", "danger")

    # ✍️ Потребує доопрацювання
    elif decision == 'needs_revision':
        instance.onboarding_status = 'revision'
        # НЕ встановлюємо archived — менеджер має пройти ще один блок
        flash("✍️ Додайте блок для доопрацювання", "info")
        db.session.commit()
        return redirect(url_for('main.edit_onboarding', manager_id=instance.manager_id))

    else:
        flash("⚠️ Невідома дія", "warning")
        return redirect(url_for('main.final_feedback', manager_id=instance.manager_id))

    db.session.commit()
    return redirect(url_for('main.managers_list'))

@bp.route('/managers/archive')
@login_required
def archived_managers():
    if current_user.role not in ['mentor', 'teamlead', 'developer']:
        return redirect(url_for('main.login'))

    managers = User.query.filter_by(role='manager').all()

    archived_pairs = []
    for manager in managers:
        # Витягуємо останній інстанс з archived=True
        instance = (
            OnboardingInstance.query
            .filter_by(manager_id=manager.id, archived=True)
            .order_by(OnboardingInstance.id.desc())
            .first()
        )
        if instance:
            archived_pairs.append((manager, instance))

    return render_template('archived_managers.html', archived_managers=archived_pairs)