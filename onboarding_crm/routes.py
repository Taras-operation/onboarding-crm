from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, abort
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime
from onboarding_crm.models import OnboardingTemplate, OnboardingInstance, OnboardingStep, User, TestResult, LoginAttempt
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from onboarding_crm.extensions import db, limiter
from onboarding_crm.utils import parse_nested_structure
from onboarding_crm.roles import Role, SUPERVISOR_ROLES
from onboarding_crm.decorators import roles_required
from onboarding_crm.permissions import (
    managers_query_for,
    visible_templates_for,
    allowed_manager_ids,
    assert_can_manage_user,
    assert_can_access_instance,
    assert_can_edit_template,
    assert_can_delete_template,
)
from onboarding_crm.services.progress import count_stages, calculate_progress
from onboarding_crm.services.master import (
    get_or_create_master, get_master, ensure_block_ids, normalize_blocks, resolve_manager_blocks,
)
from onboarding_crm.services.scoring import answer_stats, onboarding_status, block_progress, block_breakdown
from onboarding_crm.services.library import (
    library_templates, pull_sources, add_blocks_to_template, send_to_department,
)
import json
import random
import re
import copy
import os
import uuid
import secrets

import html

try:
    import bleach
except ImportError:
    bleach = None

bp = Blueprint('main', __name__)

# --- Onboarding Attachment Upload Helpers ---
ALLOWED_ATTACHMENT_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'webp',
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'txt', 'csv', 'zip'
}
MAX_ATTACHMENT_SIZE_MB = 25

def _allowed_attachment_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_ATTACHMENT_EXTENSIONS

def _attachment_kind(mimetype):
    if (mimetype or '').startswith('image/'):
        return 'image'
    if mimetype == 'application/pdf':
        return 'pdf'
    return 'file'

# --- Helper: allowed managers for current user (department-aware)

# Backwards-compatible wrappers — canonical logic now lives in onboarding_crm.permissions
def _allowed_managers_for_current_user():
    return managers_query_for(current_user)


def _visible_templates_for_current_user():
    return visible_templates_for(current_user)


def _latest_instances_for(manager_ids):
    """One query → {manager_id: latest OnboardingInstance}. Replaces the per-manager
    N+1 that ran a separate 'latest instance' query inside dashboard loops."""
    if not manager_ids:
        return {}
    rows = (OnboardingInstance.query
            .filter(OnboardingInstance.manager_id.in_(manager_ids))
            .order_by(OnboardingInstance.id.desc())
            .all())
    latest = {}
    for inst in rows:
        latest.setdefault(inst.manager_id, inst)  # first seen per manager = highest id
    return latest


def _sanitize_rich_text_html(value):
    """Allow safe Quill HTML formatting, links and lists; strip dangerous HTML."""
    if not value:
        return ''

    value = str(value)

    if bleach is None:
        # Fallback: safe, but formatting will be escaped if bleach is not installed.
        return html.escape(value)

    allowed_tags = [
        'p', 'br', 'strong', 'b', 'em', 'i', 'u',
        'h1', 'h2', 'h3',
        'ol', 'ul', 'li',
        'a', 'span', 'blockquote', 'pre', 'code'
    ]
    allowed_attrs = {
        'a': ['href', 'title', 'target', 'rel'],
        'span': ['class'],
        'p': ['class'],
        'ol': ['class'],
        'ul': ['class'],
        'li': ['class'],
    }
    allowed_protocols = ['http', 'https', 'mailto', 'tel']

    cleaned = bleach.clean(
        value,
        tags=allowed_tags,
        attributes=allowed_attrs,
        protocols=allowed_protocols,
        strip=True
    )

    # Link safety: external links should not get window.opener access.
    cleaned = bleach.linkify(
        cleaned,
        callbacks=[bleach.callbacks.nofollow, bleach.callbacks.target_blank]
    )

    return cleaned


def _sanitize_onboarding_structure(blocks):
    """Sanitize rich-text descriptions inside onboarding blocks/subblocks."""
    if isinstance(blocks, dict) and 'blocks' in blocks:
        blocks = blocks.get('blocks') or []

    if not isinstance(blocks, list):
        return []

    for block in blocks:
        if not isinstance(block, dict):
            continue

        block['description'] = _sanitize_rich_text_html(block.get('description'))

        subblocks = block.get('subblocks') or []
        if isinstance(subblocks, list):
            for subblock in subblocks:
                if isinstance(subblock, dict):
                    subblock['description'] = _sanitize_rich_text_html(subblock.get('description'))

    return blocks
# Where each role lands after login. Unknown roles fall back to DEFAULT_HOME so a valid
# login never dead-ends on a 401 (that was the `head` bug — head had no branch).
ROLE_HOME = {
    Role.DEVELOPER: 'main.developer_dashboard',
    Role.TEAMLEAD: 'main.mentor_dashboard',
    Role.HEAD: 'main.mentor_dashboard',
    Role.MENTOR: 'main.mentor_dashboard',
    Role.MANAGER: 'main.manager_dashboard',
}
DEFAULT_HOME = 'main.mentor_dashboard'


def home_for(user):
    return ROLE_HOME.get(user.role, DEFAULT_HOME)


def is_safe_url(target):
    """Only same-site, absolute-path redirects — blocks open-redirect via ?next=."""
    return bool(target) and target.startswith('/') and not target.startswith('//')


# Precomputed once. Checking a login for a non-existent user against this hash keeps the
# response time indistinguishable from a real-user wrong-password, defeating enumeration.
_DUMMY_PASSWORD_HASH = generate_password_hash('timing-equalizer-not-a-real-password')


def _record_login_attempt(user, username, success):
    """Best-effort audit row; never let logging break the login flow."""
    try:
        db.session.add(LoginAttempt(
            user_id=user.id if user else None,
            username=(username or '')[:150],
            ip=request.remote_addr,
            user_agent=(request.headers.get('User-Agent') or '')[:400],
            success=success,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute; 30 per hour", methods=['POST'])
def login():
    if request.method == 'POST':
        login_input = request.form.get('login')
        password_input = request.form.get('password') or ''

        user = User.query.filter_by(username=login_input).first()

        # Always hash-compare (dummy hash when the user is unknown) → constant-ish timing.
        stored_hash = user.password if user else _DUMMY_PASSWORD_HASH
        password_ok = check_password_hash(stored_hash, password_input)

        if user and password_ok:
            if not user.is_active:
                _record_login_attempt(user, login_input, success=False)
                return "Обліковий запис деактивовано", 403

            login_user(user)
            _record_login_attempt(user, login_input, success=True)

            next_url = request.args.get('next')
            if is_safe_url(next_url):
                return redirect(next_url)
            return redirect(url_for(home_for(user)))

        _record_login_attempt(user, login_input, success=False)
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
@roles_required(Role.DEVELOPER)
def developer_dashboard():
    # --- Tabs (single route UI) ---
    tab = (request.args.get('tab') or 'overview').strip()
    view = (request.args.get('view') or '').strip()

    # sensible defaults for Users section
    if tab == 'users' and view not in ['all', 'add']:
        view = 'all'

    # --- Create new user ---
    if request.method == 'POST':
        # allow POST to control where we redirect back
        tab = (request.form.get('tab') or tab or 'users').strip()
        view = (request.form.get('view') or view or 'add').strip()

        tg_nick = (request.form.get('tg_nick') or '').strip() or None
        role = (request.form.get('role') or '').strip()
        department = (request.form.get('department') or '').strip() or None
        position = (request.form.get('position') or '').strip() or None
        username = (request.form.get('username') or '').strip()
        password_raw = request.form.get('password') or ''

        if not role or role not in Role.values():
            flash('Некоректна роль користувача', 'danger')
            return redirect(url_for('main.developer_dashboard', tab='users', view='add'))

        if not username:
            flash('Логін (username) обов\'язковий', 'danger')
            return redirect(url_for('main.developer_dashboard', tab='users', view='add'))

        if not password_raw:
            flash('Пароль обов\'язковий', 'danger')
            return redirect(url_for('main.developer_dashboard', tab='users', view='add'))

        password = generate_password_hash(password_raw)

        # --- Determine added_by_id (who created the user)
        added_by_id = None
        if role == Role.MENTOR:
            # mentor must be linked to a teamlead
            tl_id = request.form.get('teamlead_id')
            if not tl_id:
                flash('Для ментора потрібно обрати тімліда', 'danger')
                return redirect(url_for('main.developer_dashboard', tab='users', view='add'))
            try:
                added_by_id = int(tl_id)
            except Exception:
                flash('Некоректний teamlead_id', 'danger')
                return redirect(url_for('main.developer_dashboard', tab='users', view='add'))

        elif role == Role.MANAGER:
            # manager can be linked to any mentor/teamlead (optional dropdown)
            mentor_id = request.form.get('mentor_id')
            if mentor_id:
                try:
                    added_by_id = int(mentor_id)
                except Exception:
                    flash('Некоректний mentor_id', 'danger')
                    return redirect(url_for('main.developer_dashboard', tab='users', view='add'))
            else:
                added_by_id = current_user.id

        # --- Unique username fallback ---
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
            added_by_id=added_by_id
        )

        db.session.add(new_user)
        db.session.commit()
        flash('Користувача додано', 'success')

        # after add -> usually go to list
        return redirect(url_for('main.developer_dashboard', tab='users', view='all'))

    # --- Data for GET ---
    users = User.query.order_by(User.id.desc()).all()
    teamleads = User.query.filter_by(role=Role.TEAMLEAD.value).order_by(User.id.desc()).all()
    mentors = User.query.filter_by(role=Role.MENTOR.value).order_by(User.id.desc()).all()
    templates = OnboardingTemplate.query.order_by(OnboardingTemplate.id.desc()).all()

    # Last successful login per user (for the users table in the dashboard).
    last_login_rows = (
        db.session.query(LoginAttempt.user_id, db.func.max(LoginAttempt.created_at))
        .filter(LoginAttempt.success.is_(True), LoginAttempt.user_id.isnot(None))
        .group_by(LoginAttempt.user_id)
        .all()
    )
    last_logins = {uid: ts for uid, ts in last_login_rows}

    return render_template(
        'developer_dashboard.html',
        users=users,
        teamleads=teamleads,
        mentors=mentors,
        templates=templates,
        last_logins=last_logins,
        tab=tab,
        view=view
    )


# --- Developer user management routes ---
@bp.route('/dashboard/developer/user/<int:user_id>/update', methods=['POST'])
@roles_required(Role.DEVELOPER)
def developer_user_update(user_id):
    user = User.query.get_or_404(user_id)

    # Only update safe profile fields from the form
    tg_nick = request.form.get('tg_nick')
    role = request.form.get('role')
    department = request.form.get('department')
    position = request.form.get('position')
    added_by_id = request.form.get('added_by_id')

    if tg_nick is not None:
        user.tg_nick = (tg_nick or '').strip() or None

    if role is not None and role.strip() in Role.values():
        user.role = role.strip()

    if department is not None:
        user.department = (department or '').strip() or None

    if position is not None:
        user.position = (position or '').strip() or None

    if added_by_id is not None and str(added_by_id).strip() != '':
        try:
            user.added_by_id = int(added_by_id)
        except Exception:
            flash('Некоректний added_by_id', 'danger')
            return redirect(url_for('main.developer_dashboard', tab='users', view='all'))

    db.session.commit()
    flash('Дані користувача оновлено', 'success')
    return redirect(url_for('main.developer_dashboard', tab='users', view='all'))


@bp.route('/dashboard/developer/user/<int:user_id>/reset_password', methods=['POST'])
@roles_required(Role.DEVELOPER)
def developer_user_reset_password(user_id):
    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password') or ''
    if not new_password:
        flash('Новий пароль не може бути порожнім', 'danger')
        return redirect(url_for('main.developer_dashboard', tab='users', view='all'))

    user.password = generate_password_hash(new_password)
    db.session.commit()
    flash('Пароль оновлено', 'success')
    return redirect(url_for('main.developer_dashboard', tab='users', view='all'))


@bp.route('/dashboard/developer/user/<int:user_id>/delete', methods=['POST'])
@roles_required(Role.DEVELOPER)
def developer_user_delete(user_id):
    user = User.query.get_or_404(user_id)

    # Don't allow deleting yourself to avoid locking out
    if user.id == current_user.id:
        flash('Неможливо видалити самого себе', 'danger')
        return redirect(url_for('main.developer_dashboard', tab='users', view='all'))

    try:
        db.session.delete(user)
        db.session.commit()
        flash('Користувача видалено', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Помилка при видаленні: {str(e)}', 'danger')

    return redirect(url_for('main.developer_dashboard', tab='users', view='all'))


@bp.route('/dashboard/developer/user/<int:user_id>/toggle_active', methods=['POST'])
@roles_required(Role.DEVELOPER)
def developer_user_toggle_active(user_id):
    user = User.query.get_or_404(user_id)

    # Don't allow disabling yourself
    if user.id == current_user.id:
        flash('Неможливо деактивувати самого себе', 'danger')
        return redirect(url_for('main.developer_dashboard', tab='users', view='all'))

    user.is_active = not bool(user.is_active)
    db.session.commit()
    flash('Статус користувача змінено', 'success')
    return redirect(url_for('main.developer_dashboard', tab='users', view='all'))

@bp.route('/dashboard/mentor')
@roles_required(Role.MENTOR, Role.TEAMLEAD, Role.HEAD)
def mentor_dashboard():
    # 1. Отримуємо список менеджерів (department-aware, single source)
    managers = managers_query_for(current_user).all()
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

    # 4. Прогрес по кожному інстансу (stage-aware, single source)
    progress_list = [calculate_progress(i) for i in active_instances if count_stages(i.structure) > 0]
    average_progress = round(sum(progress_list) / len(progress_list), 1) if progress_list else 0

    return render_template(
        'mentor_dashboard.html',
        managers=managers,
        active_onboardings=len(active_instances),
        archived_count=archived_count,
        average_progress=average_progress
    )

@bp.route('/managers/list')
@roles_required(Role.MENTOR, Role.TEAMLEAD, Role.DEVELOPER, Role.HEAD)
def managers_list():
    # 🔹 1. Базовая выборка менеджеров по ролям (department-aware, single source)
    managers = managers_query_for(current_user).all()

    # 🔹 2. Latest instance per manager in ONE query (was N+1: one query per manager)
    latest_by_manager = _latest_instances_for([m.id for m in managers])

    filtered_managers = []
    for manager in managers:
        instance = latest_by_manager.get(manager.id)
        manager.latest_instance = instance

        # Если онбординг существует, но в архиве — пропускаем
        if instance and instance.archived:
            continue

        manager.total_steps_calculated = count_stages(instance.structure) if instance else 0
        manager.status = onboarding_status(instance)
        filtered_managers.append(manager)

    # 🔹 3. Рендер страницы
    return render_template('managers_list.html', managers=filtered_managers)

@bp.route('/manager/statistics')
@roles_required(Role.MANAGER)
def manager_statistics():
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
@roles_required(Role.MENTOR, Role.TEAMLEAD)
def add_manager():
    # 🟢 Формуємо список менторів тільки з того ж відділу
    if current_user.role == Role.MENTOR:
        mentors = [current_user]
    elif current_user.role == Role.TEAMLEAD:
        mentors = User.query.filter(
            User.role.in_([Role.MENTOR.value, Role.TEAMLEAD.value]),
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
            role=Role.MANAGER.value,
            username=username,
            password=password,
            added_by_id=int(mentor_id)
        )
        db.session.add(new_user)
        db.session.commit()

        # Step 2 of the new flow: choose which master blocks this manager gets.
        return redirect(url_for('main.select_manager_blocks', manager_id=new_user.id))

    return render_template('add_manager.html', mentors=mentors)


@bp.route('/onboarding/manager/<int:manager_id>/blocks', methods=['GET', 'POST'])
@roles_required(Role.MENTOR, Role.TEAMLEAD, Role.DEVELOPER)
def select_manager_blocks(manager_id):
    """Step 2 / edit: pick which master blocks this manager receives (checkboxes)."""
    assert_can_manage_user(manager_id)
    manager = User.query.get_or_404(manager_id)
    master = get_or_create_master(manager.department, created_by=current_user.id)
    blocks = normalize_blocks(master.structure)  # each block has a stable id + title

    instance = (OnboardingInstance.query
                .filter_by(manager_id=manager_id)
                .order_by(OnboardingInstance.id.desc())
                .first())
    current_ids = set((instance.selected_block_ids if instance else []) or [])

    if request.method == 'POST':
        chosen = set(request.form.getlist('block_ids'))

        # Never drop a block the manager already completed (keeps results consistent).
        completed_ids = set((instance.locked_blocks or {}).keys()) if instance else set()
        chosen |= completed_ids

        master_ids_in_order = [b['id'] for b in blocks if b.get('id')]
        valid_master_ids = set(master_ids_in_order)
        existing = [bid for bid in ((instance.selected_block_ids or []) if instance else [])
                    if bid in chosen and bid in valid_master_ids]
        # Preserve the positions of already-selected blocks; append newly chosen ones in
        # master order — so a completed block's index never shifts under it.
        added = [bid for bid in master_ids_in_order if bid in chosen and bid not in existing]
        ordered = existing + added

        by_id = {b['id']: b for b in blocks if b.get('id')}
        snapshot = [by_id[bid] for bid in ordered if bid in by_id]

        if not ordered:
            flash('Оберіть хоча б один блок', 'warning')
            return redirect(url_for('main.select_manager_blocks', manager_id=manager_id))

        if instance:
            instance.selected_block_ids = ordered
            instance.master_template_id = master.id
            instance.structure = {'blocks': snapshot}
        else:
            instance = OnboardingInstance(
                name=f"Онбординг для {(manager.tg_nick or manager.username or '').lstrip('@')}",
                manager_id=manager.id,
                mentor_id=current_user.id,
                master_template_id=master.id,
                selected_block_ids=ordered,
                structure={'blocks': snapshot},
                onboarding_step=0,
            )
            db.session.add(instance)

        # keep the per-user mirror fields roughly in sync
        manager.onboarding_name = instance.name
        manager.onboarding_status = 'in_progress'
        manager.onboarding_step = 0
        manager.onboarding_step_total = len(ordered)
        manager.onboarding_start = datetime.utcnow()
        db.session.commit()

        flash(f'Менеджеру призначено блоків: {len(ordered)}', 'success')
        return redirect(url_for('main.managers_list'))

    return render_template('select_blocks.html', manager=manager, blocks=blocks, current_ids=current_ids)

@bp.route('/onboarding/plans')
@roles_required(Role.MENTOR, Role.TEAMLEAD, Role.DEVELOPER, Role.HEAD)
def onboarding_plans():
    # New model: one master per department + managers with their selected block counts.
    master = get_master(current_user.department)
    master_block_count = len(normalize_blocks(master.structure)) if master else 0

    managers = managers_query_for(current_user).all()
    latest_by_manager = _latest_instances_for([m.id for m in managers])

    rows = []
    for m in managers:
        instance = latest_by_manager.get(m.id)
        selected = len(instance.selected_block_ids or []) if instance else 0
        completed = (instance.onboarding_step or 0) if instance else 0
        rows.append({
            'manager': m,
            'instance': instance,
            'selected': selected,
            'completed': completed,
            'mentor': (m.added_by.tg_nick if m.added_by else '—'),
        })

    return render_template(
        "onboarding_plans.html",
        master=master,
        master_block_count=master_block_count,
        rows=rows,
    )

@bp.route('/onboarding/editor')
@roles_required(Role.MENTOR, Role.TEAMLEAD)
def onboarding_editor():
    managers = _allowed_managers_for_current_user().all()
    return render_template('add_template.html', managers=managers)


@bp.route('/onboarding/master')
@roles_required(Role.MENTOR, Role.TEAMLEAD, Role.HEAD, Role.DEVELOPER)
def master_onboarding():
    """Open a department's single master onboarding (all blocks) in the editor.
    Devops picks the department via ?department=; everyone else edits their own."""
    dept = current_user.department
    if current_user.role == Role.DEVELOPER:
        dept = (request.args.get('department') or '').strip()
        if not dept:
            flash('Оберіть відділ', 'warning')
            return redirect(url_for('main.devops_onboardings'))
    master = get_or_create_master(dept, created_by=current_user.id)
    return redirect(url_for('main.add_onboarding_template', template_id=master.id))


# --- Onboarding block attachment upload endpoint ---
@bp.route('/onboarding/attachment/upload', methods=['POST'])
@login_required
def upload_onboarding_attachment():
    if current_user.role not in SUPERVISOR_ROLES:
        return jsonify({'ok': False, 'message': 'Немає прав на завантаження файлів'}), 403

    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'ok': False, 'message': 'Файл не передано'}), 400

    if not _allowed_attachment_file(file.filename):
        return jsonify({'ok': False, 'message': 'Недозволений тип файлу'}), 400

    file.seek(0, os.SEEK_END)
    size_bytes = file.tell()
    file.seek(0)

    max_bytes = MAX_ATTACHMENT_SIZE_MB * 1024 * 1024
    if size_bytes > max_bytes:
        return jsonify({'ok': False, 'message': f'Файл завеликий. Максимум {MAX_ATTACHMENT_SIZE_MB} MB'}), 400

    original_name = secure_filename(file.filename)
    ext = original_name.rsplit('.', 1)[1].lower()
    stored_name = f"{uuid.uuid4().hex}.{ext}"

    upload_dir = os.path.join(os.getcwd(), 'onboarding_crm', 'static', 'uploads', 'onboarding')
    os.makedirs(upload_dir, exist_ok=True)

    file_path = os.path.join(upload_dir, stored_name)
    file.save(file_path)

    file_url = url_for('static', filename=f'uploads/onboarding/{stored_name}')

    return jsonify({
        'ok': True,
        'attachment': {
            'name': original_name,
            'url': file_url,
            'type': file.mimetype or 'application/octet-stream',
            'kind': _attachment_kind(file.mimetype),
            'size': size_bytes
        }
    })

@bp.route('/onboarding/template/add', methods=['GET', 'POST'])
@roles_required(Role.MENTOR, Role.TEAMLEAD, Role.DEVELOPER)
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

        structure = _sanitize_onboarding_structure(structure)
        # Ensure every block carries a stable id (belt-and-suspenders next to the editor JS).
        structure = ensure_block_ids(structure)['blocks']

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
                    assert_can_edit_template(tpl)
                    tpl.name = name
                    tpl.structure = payload
                    # ✅ FIX: department only for department templates (not library ones)
                    if not getattr(tpl, 'is_library', False) and not getattr(tpl, 'department', None):
                        tpl.department = current_user.department
                    db.session.commit()
                    if getattr(tpl, 'is_library', False):
                        return redirect(url_for('main.devops_library_template', id=tpl.id))
                    if current_user.role == Role.DEVELOPER:
                        return redirect(url_for('main.devops_onboardings'))
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
        assert_can_edit_template(template)
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
@roles_required(Role.MENTOR, Role.TEAMLEAD)
def edit_onboarding(manager_id):
    # Only a manager the current user supervises.
    assert_can_manage_user(manager_id)

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

        new_blocks = _sanitize_onboarding_structure(new_blocks)

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
@roles_required(Role.MENTOR, Role.TEAMLEAD)
def copy_user_onboarding(id):
    original = User.query.get_or_404(id)
    if original.role != Role.MANAGER:
        flash('Цей користувач не є менеджером.', 'warning')
        return redirect(url_for('main.onboarding_plans'))

    # Only copy a manager the current user actually supervises.
    assert_can_manage_user(original.id)

    # Guarantee a unique username (…_copy, _copy2, _copy3, …) — the old code always
    # appended "_copy" and hit the unique constraint (500) on the second copy.
    base_username = f"{original.username}_copy"
    username = base_username
    counter = 2
    while User.query.filter_by(username=username).first():
        username = f"{base_username}{counter}"
        counter += 1

    # NEVER copy the original's password hash — that would hand out a working login.
    # Issue a fresh random temporary password and surface it once to the creator.
    temp_password = secrets.token_urlsafe(9)

    new_user = User(
        tg_nick=original.tg_nick,
        department=original.department,
        position=original.position,
        username=username,
        password=generate_password_hash(temp_password),
        role=Role.MANAGER.value,
        added_by_id=current_user.id,
        onboarding_name=(original.onboarding_name or original.username or 'Онбординг') + ' (копія)',
        onboarding_status='Не розпочато',
        onboarding_step=0,
        onboarding_step_total=original.onboarding_step_total
    )
    db.session.add(new_user)
    db.session.commit()
    flash(
        f"Створено «{username}». Тимчасовий пароль: {temp_password} — "
        f"збережіть його зараз, він більше не відобразиться.",
        "success"
    )
    return redirect(url_for('main.edit_onboarding', manager_id=new_user.id))

@bp.route('/onboarding/save', methods=['POST'])
@roles_required(Role.MENTOR, Role.TEAMLEAD)
def save_onboarding():
    data = request.get_json()
    manager_id = data.get('manager_id')
    blocks = data.get('blocks', [])

    # Department-aware ownership check (JSON endpoint → JSON 403)
    if manager_id:
        try:
            _mid = int(manager_id)
        except Exception:
            _mid = None
        if _mid is None or _mid not in allowed_manager_ids(current_user):
            return {'message': 'Немає прав призначати онбординг цьому менеджеру'}, 403

    if not blocks:
        return {'message': 'Порожній онбординг'}, 400

    payload = {'blocks': blocks}

    if manager_id:
        user = User.query.get(manager_id)
        if not user or user.role != Role.MANAGER:
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

@bp.route('/onboarding/template/delete/<int:id>', methods=['POST', 'DELETE'])
@roles_required(SUPERVISOR_ROLES)
def delete_onboarding_template(id):
    template = OnboardingTemplate.query.get_or_404(id)
    # Only the owner, a teamlead/head of the template's department, or a developer.
    # Global templates: developer only.
    assert_can_delete_template(template)
    # Видаляємо всі кроки, пов’язані з шаблоном
    OnboardingStep.query.filter_by(template_id=template.id).delete()
    db.session.delete(template)
    db.session.commit()
    return '', 204


@bp.route('/onboarding/template/<int:id>/share', methods=['POST'])
@roles_required(Role.DEVELOPER)
def share_onboarding_template(id):
    template = OnboardingTemplate.query.get_or_404(id)

    is_global = request.form.get('is_global') == 'on'
    shared_departments = [d.strip() for d in request.form.getlist('shared_departments') if d and d.strip()]
    shared_departments = list(dict.fromkeys(shared_departments))

    if hasattr(template, 'is_global'):
        template.is_global = bool(is_global)

    if hasattr(template, 'shared_departments'):
        template.shared_departments = [] if is_global else shared_departments
    else:
        flash('Поле shared_departments відсутнє в моделі OnboardingTemplate', 'warning')
        return redirect(url_for('main.developer_dashboard', tab='templates'))

    db.session.commit()
    flash('Доступи до шаблону оновлено', 'success')
    return redirect(url_for('main.developer_dashboard', tab='templates'))


@bp.route('/onboarding/template/<int:id>/duplicate', methods=['POST'])
@roles_required(SUPERVISOR_ROLES)
def duplicate_onboarding_template(id):
    template = OnboardingTemplate.query.get_or_404(id)
    # You can only duplicate a template you're allowed to see (department isolation).
    assert_can_edit_template(template)

    structure_copy = copy.deepcopy(template.structure) if template.structure is not None else None

    new_template = OnboardingTemplate(
        name=f"{template.name or 'Template'} (Copy)",
        structure=structure_copy,
        department=getattr(current_user, 'department', None),
        created_by=current_user.id
    )

    if hasattr(new_template, 'is_global'):
        new_template.is_global = False
    if hasattr(new_template, 'shared_departments'):
        new_template.shared_departments = []
    if hasattr(new_template, 'is_copy'):
        new_template.is_copy = True
    if hasattr(new_template, 'source_template_id'):
        new_template.source_template_id = template.id

    db.session.add(new_template)
    db.session.commit()

    flash('Шаблон дубльовано', 'success')
    return redirect(url_for('main.developer_dashboard', tab='templates'))

@bp.route('/onboarding/user/delete/<int:id>', methods=['DELETE'])
@roles_required(Role.TEAMLEAD, Role.DEVELOPER)
def delete_user_onboarding(id):
    user = User.query.get_or_404(id)

    # 🔐 Teamlead — тільки менеджери, і тільки свої (mentor вже відсіяно декоратором)
    if current_user.role == Role.TEAMLEAD:
        if user.role != Role.MANAGER:
            return {'message': 'Тімлід може видаляти лише менеджерів'}, 403
        if user.id not in allowed_manager_ids(current_user):
            return {'message': 'Немає прав на видалення цього користувача'}, 403

    try:
        db.session.delete(user)  # 🧼 Каскад сам видалить всі пов’язані записи
        db.session.commit()
        return '', 204
    except Exception as e:
        db.session.rollback()
        return {'message': f'Помилка при видаленні: {str(e)}'}, 500
    
@bp.route('/onboarding/instance/delete/<int:onboarding_id>', methods=['DELETE'])
@roles_required(Role.MENTOR, Role.TEAMLEAD, Role.HEAD, Role.DEVELOPER)
def delete_onboarding_instance(onboarding_id):
    instance = OnboardingInstance.query.get_or_404(onboarding_id)

    # 🔐 Ownership (JSON endpoint → JSON 403)
    if current_user.role != Role.DEVELOPER and instance.manager_id not in allowed_manager_ids(current_user):
        return {'message': 'У вас немає прав на видалення цього онбордингу'}, 403

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
@roles_required(Role.MANAGER)
def manager_dashboard():
    # 1. Последний онбординг-инстанс менеджера
    instance = (OnboardingInstance.query
                .filter_by(manager_id=current_user.id)
                .order_by(OnboardingInstance.id.desc())
                .first())
    if not instance:
        return "Онбординг ще не призначено", 404

    # New model: blocks are resolved live from the department master (snapshot if the
    # block is already completed). Progress is keyed by stable block id.
    stage_blocks = [b for b in resolve_manager_blocks(instance) if b.get("type") == "stage"]

    progress = instance.test_progress if isinstance(instance.test_progress, dict) else {}

    steps_meta = []
    for i, b in enumerate(stage_blocks):
        bid = b.get("id")
        p = progress.get(bid, {}) if bid else {}
        steps_meta.append({
            "index": i,
            "id": bid,
            "title": b.get("title") or f"Крок {i + 1}",
            "description": b.get("description") or "",
            "started": bool(p.get("started")),
            "completed": bool(p.get("completed")),
            "url": url_for('main.manager_step', step=i),
        })

    # Sequential unlock: first step always open; each next opens once the previous is done.
    for i, meta in enumerate(steps_meta):
        meta["accessible"] = (i == 0) or steps_meta[i - 1]["completed"]

    current_step = next((m["index"] for m in steps_meta if not m["completed"]),
                        max(len(steps_meta) - 1, 0))

    return render_template(
        'manager_dashboard.html',
        blocks=stage_blocks,
        steps_meta=steps_meta,
        current_step=current_step,
        status=onboarding_status(instance),
    )

@bp.route('/manager_step/<int:step>', methods=['GET', 'POST'])
@roles_required(Role.MANAGER)
def manager_step(step):
    from flask import jsonify, make_response

    instance = (OnboardingInstance.query
                .filter_by(manager_id=current_user.id)
                .order_by(OnboardingInstance.id.desc())
                .first())
    if not instance:
        return redirect(url_for('main.manager_dashboard'))

    # New model: blocks are the manager's selected subset, resolved live from the master
    # (snapshot for completed ones). Progress is keyed by stable block id.
    stage_blocks = [b for b in resolve_manager_blocks(instance) if b.get("type") == "stage"]
    total_steps = len(stage_blocks)
    if step >= total_steps:
        return redirect(url_for('main.manager_dashboard'))

    block = stage_blocks[step]
    block_id = block.get('id') or str(step)

    # --- Прогресс (copy → new object so JSON writes are detected) ---
    progress = dict(instance.test_progress) if isinstance(instance.test_progress, dict) else {}

    step_key = block_id
    step_progress = progress.get(step_key, {})
    raw_started = bool(step_progress.get('started', False))
    raw_completed = bool(step_progress.get('completed', False))

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

        # Complete this step and FREEZE its content: snapshot the block into locked_blocks
        # so later edits to the master don't rewrite what the manager already did.
        progress[step_key] = {'started': True, 'completed': True}
        locked = dict(instance.locked_blocks) if isinstance(instance.locked_blocks, dict) else {}
        locked[block_id] = block

        instance.test_progress = progress
        instance.locked_blocks = locked

        completed_count = sum(1 for v in progress.values() if isinstance(v, dict) and v.get('completed'))
        instance.onboarding_step = completed_count
        current_user.onboarding_step = completed_count
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
@roles_required(Role.MENTOR, Role.TEAMLEAD, Role.HEAD, Role.DEVELOPER)
def manager_results(manager_id, onboarding_id):
    manager = User.query.get(manager_id)
    instance = OnboardingInstance.query.get(onboarding_id)

    if not manager or not instance:
        flash("❌ Менеджер або онбординг не знайдено", "danger")
        return redirect(url_for('main.managers_list'))

    if instance.manager_id != manager.id:
        flash("⛔️ Онбординг не належить цьому менеджеру", "danger")
        return redirect(url_for('main.managers_list'))

    # IDOR: the viewer must actually supervise this manager
    assert_can_access_instance(instance)

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

    locked = bool(instance.archived)  # decided → review-only, no re-grading / re-decision
    show_popup = all_blocks_completed and (not open_results or all_open_checked) and not locked

    return render_template(
        'manager_results.html',
        manager=manager,
        instance=instance,
        choice_results=choice_results,
        open_results=open_results,
        step=instance.onboarding_step,
        show_popup=show_popup,
        locked=locked,
        status=onboarding_status(instance),
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

    blocks = [b for b in resolve_manager_blocks(instance) if b.get('type') == 'stage']
    if step >= len(blocks):
        return jsonify({'status': 'error'}), 404
    block_id = blocks[step].get('id') or str(step)

    progress = dict(instance.test_progress) if isinstance(instance.test_progress, dict) else {}
    prev = dict(progress.get(block_id, {}))
    prev['started'] = True  # только помечаем started, completed не трогаем
    progress[block_id] = prev

    instance.test_progress = progress
    db.session.commit()

    resp = jsonify({'status': 'ok'})
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

    blocks = [b for b in resolve_manager_blocks(instance) if b.get('type') == 'stage']
    if step >= len(blocks):
        return jsonify({'status': 'error'}), 404
    block = blocks[step]
    block_id = block.get('id') or str(step)

    progress = dict(instance.test_progress) if isinstance(instance.test_progress, dict) else {}
    prev = dict(progress.get(block_id, {}))
    prev['completed'] = True
    prev['started'] = prev.get('started', True)
    progress[block_id] = prev

    # Freeze the completed block (snapshot) so master edits don't rewrite it.
    locked = dict(instance.locked_blocks) if isinstance(instance.locked_blocks, dict) else {}
    locked[block_id] = block

    instance.test_progress = progress
    instance.locked_blocks = locked

    completed_count = sum(1 for v in progress.values() if isinstance(v, dict) and v.get('completed'))
    instance.onboarding_step = completed_count
    current_user.onboarding_step = completed_count
    db.session.commit()

    resp = jsonify({'status': 'ok'})
    resp.delete_cookie(f"step_started_{step}", path=f"/manager_step/{step}")
    return resp

@bp.route('/update_result/<int:result_id>', methods=['POST'])
@roles_required(SUPERVISOR_ROLES)
def update_result(result_id):
    """Автоматичне збереження фідбеку (чернетки) для відкритих питань."""
    result = TestResult.query.get_or_404(result_id)

    # 🔐 Ownership: only over a supervised manager's results (JSON endpoint)
    if current_user.role != Role.DEVELOPER and result.manager_id not in allowed_manager_ids(current_user):
        return jsonify({'error': 'Access denied'}), 403

    # 🔒 Closed onboarding — grading is read-only.
    if result.onboarding_instance and result.onboarding_instance.archived:
        return jsonify({'error': 'Онбординг закрито'}), 409

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
@roles_required(SUPERVISOR_ROLES)
def publish_feedback(manager_id):
    """Публікація фідбеку по ВСІМ відкритим питанням менеджера"""
    if current_user.role != Role.DEVELOPER and manager_id not in allowed_manager_ids(current_user):
        return jsonify({'error': 'Access denied'}), 403

    # 🔒 Closed onboarding — no re-publishing feedback.
    _latest = (OnboardingInstance.query.filter_by(manager_id=manager_id)
               .order_by(OnboardingInstance.id.desc()).first())
    if _latest and _latest.archived:
        return jsonify({'error': 'Онбординг закрито'}), 409

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
@roles_required(SUPERVISOR_ROLES)
def final_feedback(manager_id):
    """Фінальний фідбек після перевірки всіх етапів онбордингу"""
    # Only over a supervised manager
    assert_can_manage_user(manager_id)

    # --- Отримуємо останній інстанс онбордингу
    instance = (OnboardingInstance.query
                .filter_by(manager_id=manager_id)
                .order_by(OnboardingInstance.id.desc())
                .first())

    if not instance:
        flash("❌ Онбординг не знайдено", "danger")
        return redirect(url_for('main.managers_list'))

    results = TestResult.query.filter_by(onboarding_instance_id=instance.id).all()
    test_results = [r for r in results if r.is_correct is not None]
    open_questions = [r for r in results if r.is_correct is None]

    stats = answer_stats(instance)
    status = onboarding_status(instance)
    breakdown = block_breakdown(instance)
    weak_blocks = [b for b in breakdown if b['verdict'] == 'redo']

    overall = stats['overall_pct'] if stats['overall_pct'] is not None else 100
    if overall >= 71:
        final_recommendation = "✅ Пройдено"
    elif overall >= 41:
        final_recommendation = "🟠 Потребує доопрацювання"
    else:
        final_recommendation = "❌ Не пройдено"

    return render_template(
        'final_feedback.html',
        manager=User.query.get(manager_id),
        instance=instance,
        open_questions=open_questions,
        stats=stats,
        status=status,
        breakdown=breakdown,
        weak_blocks=weak_blocks,
        locked=bool(instance.archived),          # decided → read-only
        final_recommendation=final_recommendation,
    )

VALID_FINAL_DECISIONS = {'approved', 'rejected', 'needs_revision'}


@bp.route('/final_decision', methods=['POST'])
@roles_required(SUPERVISOR_ROLES)
def final_decision():
    instance_id = request.form.get('instance_id')
    decision = request.form.get('decision')
    comment = request.form.get('comment', '')  # опціональний фідбек

    # Whitelist the decision at the door — an arbitrary string must never slip through.
    if decision not in VALID_FINAL_DECISIONS:
        flash("⚠️ Невідома дія", "warning")
        return redirect(url_for('main.managers_list'))

    instance = OnboardingInstance.query.get(instance_id)

    if not instance:
        flash("Онбординг не знайдено", "danger")
        return redirect(url_for('main.managers_list'))

    # A manager must not be able to decide their own onboarding: only a supervisor of
    # this instance's manager may act on it.
    assert_can_access_instance(instance)

    # A closed (archived) onboarding cannot be re-decided.
    if instance.archived:
        flash("Онбординг вже закрито — повторне рішення неможливе", "warning")
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
@roles_required(Role.MENTOR, Role.TEAMLEAD, Role.HEAD, Role.DEVELOPER)
def archived_managers():
    managers = managers_query_for(current_user).all()

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


# ─────────────────────────────────────────────
# 🔹 Devops: бібліотека шаблонів + конструктор (super-admin)
# ─────────────────────────────────────────────
def _all_departments():
    rows = db.session.query(User.department).filter(User.department.isnot(None)).distinct().all()
    return sorted({(d[0] or '').strip() for d in rows if (d[0] or '').strip()})


@bp.route('/devops/library')
@roles_required(Role.DEVELOPER)
def devops_library():
    templates = OnboardingTemplate.query.order_by(OnboardingTemplate.id.desc()).all()
    rows = []
    for t in templates:
        kind = 'library' if t.is_library else ('master' if t.is_master else 'legacy')
        rows.append({'tpl': t, 'kind': kind, 'blocks': len(normalize_blocks(t.structure))})
    return render_template('devops_library.html', rows=rows)


@bp.route('/devops/library/new', methods=['POST'])
@roles_required(Role.DEVELOPER)
def devops_library_new():
    name = (request.form.get('name') or '').strip() or 'Новий шаблон'
    t = OnboardingTemplate(name=name, structure={'blocks': []}, is_library=True,
                           created_by=current_user.id, department=None)
    db.session.add(t)
    db.session.commit()
    return redirect(url_for('main.devops_library_template', id=t.id))


@bp.route('/devops/library/<int:id>')
@roles_required(Role.DEVELOPER)
def devops_library_template(id):
    tpl = OnboardingTemplate.query.get_or_404(id)
    blocks = normalize_blocks(tpl.structure)
    sources = pull_sources(exclude_id=id)
    source_id = request.args.get('source', type=int)
    source = OnboardingTemplate.query.get(source_id) if source_id else None
    source_blocks = normalize_blocks(source.structure) if source else []
    return render_template('devops_constructor.html', tpl=tpl, blocks=blocks,
                           sources=sources, source=source, source_blocks=source_blocks,
                           departments=_all_departments())


@bp.route('/devops/library/<int:id>/pull-blocks', methods=['POST'])
@roles_required(Role.DEVELOPER)
def devops_pull_blocks(id):
    tpl = OnboardingTemplate.query.get_or_404(id)
    source = OnboardingTemplate.query.get_or_404(request.form.get('source_template_id', type=int))
    block_ids = request.form.getlist('block_ids')
    if not block_ids:
        flash('Оберіть блоки для додавання', 'warning')
        return redirect(url_for('main.devops_library_template', id=id, source=source.id))
    n = add_blocks_to_template(tpl, source, block_ids)
    flash(f'Додано блоків: {n}', 'success')
    return redirect(url_for('main.devops_library_template', id=id))


@bp.route('/devops/library/<int:id>/send-to-department', methods=['POST'])
@roles_required(Role.DEVELOPER)
def devops_send_to_department(id):
    tpl = OnboardingTemplate.query.get_or_404(id)
    dept = (request.form.get('department') or '').strip()
    mode = request.form.get('mode') if request.form.get('mode') in ('append', 'replace') else 'append'
    if not dept:
        flash('Оберіть відділ', 'warning')
        return redirect(url_for('main.devops_library_template', id=id))
    master, n = send_to_department(tpl, dept, mode=mode, created_by=current_user.id)
    verb = 'замінено' if mode == 'replace' else 'додано'
    flash(f'Надіслано у відділ «{dept}»: {verb} {n} блок(ів).', 'success')
    return redirect(url_for('main.devops_library_template', id=id))


@bp.route('/devops/library/<int:id>/delete', methods=['POST'])
@roles_required(Role.DEVELOPER)
def devops_library_delete(id):
    tpl = OnboardingTemplate.query.get_or_404(id)
    OnboardingStep.query.filter_by(template_id=tpl.id).delete()
    db.session.delete(tpl)
    db.session.commit()
    flash('Шаблон видалено', 'success')
    return redirect(url_for('main.devops_library'))


@bp.route('/devops/onboardings')
@roles_required(Role.DEVELOPER)
def devops_onboardings():
    masters = (OnboardingTemplate.query.filter_by(is_master=True)
               .order_by(OnboardingTemplate.department).all())
    master_rows = [{'dept': m.department, 'blocks': len(normalize_blocks(m.structure)), 'id': m.id}
                   for m in masters]

    managers = User.query.filter_by(role=Role.MANAGER.value).order_by(User.department).all()
    latest = _latest_instances_for([m.id for m in managers])
    mgr_rows = [{'manager': m, 'instance': latest.get(m.id), 'status': onboarding_status(latest.get(m.id))}
                for m in managers]
    return render_template('devops_onboardings.html', master_rows=master_rows, mgr_rows=mgr_rows)


# ─────────────────────────────────────────────
# 🔹 Error handlers (app-wide, registered via blueprint)
# ─────────────────────────────────────────────
@bp.app_errorhandler(403)
def forbidden(error):
    return render_template('errors/403.html'), 403


@bp.app_errorhandler(404)
def not_found(error):
    return render_template('errors/404.html'), 404