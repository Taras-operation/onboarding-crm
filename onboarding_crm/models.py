from onboarding_crm.extensions import db
from flask_login import UserMixin
from datetime import datetime
import json
from sqlalchemy.dialects.postgresql import JSONB  # ✅ для test_progress

# ─────────────────────────────────────────────
# 🔹 Модель користувача (менеджер, ментор, ТЛ)
# ─────────────────────────────────────────────
class User(db.Model, UserMixin):
    __tablename__ = 'user'
    
    id = db.Column(db.Integer, primary_key=True)
    tg_nick = db.Column(db.String(150))
    department = db.Column(db.String(150))
    position = db.Column(db.String(100))
    username = db.Column(db.String(150), unique=True)
    password = db.Column(db.String(256))
    role = db.Column(db.String(50))

    added_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'))
    added_by = db.relationship('User', remote_side=[id])

    onboarding_status = db.Column(db.String(100), default='Не розпочато')
    onboarding_step = db.Column(db.Integer, default=0)
    onboarding_step_total = db.Column(db.Integer, default=0)
    onboarding_name = db.Column(db.String(150))
    onboarding_start = db.Column(db.DateTime)
    onboarding_end = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 🔹 Каскадное удаление всех связанных онбордингов и тестов
    manager_onboardings = db.relationship(
        'OnboardingInstance',
        foreign_keys='OnboardingInstance.manager_id',
        cascade='all, delete-orphan',
        passive_deletes=True
    )

    mentor_onboardings = db.relationship(
        'OnboardingInstance',
        foreign_keys='OnboardingInstance.mentor_id',
        cascade='all, delete-orphan',
        passive_deletes=True
    )

    test_results = db.relationship(
        'TestResult',
        backref='manager',
        cascade='all, delete-orphan',
        passive_deletes=True
    )

    @property
    def total_steps(self):
        instance = OnboardingInstance.query.filter_by(manager_id=self.id).first()
        if not instance or not instance.structure:
            return 0
        try:
            structure = instance.structure
            if isinstance(structure, str):
                structure = json.loads(structure)
            blocks = structure.get("blocks") if isinstance(structure, dict) else structure
            return sum(1 for b in blocks if b.get("type") == "stage")
        except Exception as e:
            print(f"[User.total_steps] JSON error for user {self.id}: {e}")
            return 0


# ─────────────────────────────────────────────
# 🔹 Шаблон онбордингу
# ─────────────────────────────────────────────
class OnboardingTemplate(db.Model):
    __tablename__ = 'onboarding_template'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    structure = db.Column(db.JSON)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    steps = db.relationship('OnboardingStep', backref='template', cascade='all, delete-orphan', lazy=True)


# ─────────────────────────────────────────────
# 🔹 Етап шаблону
# ─────────────────────────────────────────────
class OnboardingStep(db.Model):
    __tablename__ = 'onboarding_step'
    
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('onboarding_template.id', ondelete='CASCADE'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    order = db.Column(db.Integer)

    step_type = db.Column(db.String(50))  # тип: "text" або "test"
    test = db.relationship('OnboardingTest', uselist=False, backref='step', cascade='all, delete-orphan')


# ─────────────────────────────────────────────
# 🔹 Тест до етапу
# ─────────────────────────────────────────────
class OnboardingTest(db.Model):
    __tablename__ = 'onboarding_test'
    
    id = db.Column(db.Integer, primary_key=True)
    step_id = db.Column(db.Integer, db.ForeignKey('onboarding_step.id', ondelete='CASCADE'), nullable=False)
    question = db.Column(db.String(255), nullable=False)
    options = db.Column(db.JSON)
    correct_answer = db.Column(db.String(255))


# ─────────────────────────────────────────────
# 🔹 Індивідуальний онбординг
# ─────────────────────────────────────────────
class OnboardingInstance(db.Model):
    __tablename__ = 'onboarding_instance'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    manager_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    mentor_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    structure = db.Column(db.JSON, nullable=False)

    # ✅ Новое поле: прогресс тестов по шагам
    # Пример: {"0": {"started": true, "completed": true}, "1": {...}}
    test_progress = db.Column(JSONB, nullable=True, default=dict)

    onboarding_step = db.Column(db.Integer, default=0)
    onboarding_step_total = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    test_results = db.relationship(
        'TestResult',
        backref='onboarding_instance',
        cascade='all, delete-orphan',
        passive_deletes=True
    )


# ─────────────────────────────────────────────
# 🔹 Результати тестів
# ─────────────────────────────────────────────
class TestResult(db.Model):
    __tablename__ = 'test_result'

    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    onboarding_instance_id = db.Column(db.Integer, db.ForeignKey('onboarding_instance.id', ondelete='CASCADE'))

    question = db.Column(db.String(512), nullable=False)
    correct_answer = db.Column(db.String(512), nullable=True)
    selected_answer = db.Column(db.String(512), nullable=True)

    # ✅ None = відкриті питання (очікують перевірки)
    is_correct = db.Column(db.Boolean, nullable=True)

    # 🔥 Фідбек від ментора
    feedback = db.Column(db.Text, nullable=True)

    # ✅ Нове поле: оцінено як зараховано/не зараховано
    approved = db.Column(db.Boolean, nullable=True)

    step = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)