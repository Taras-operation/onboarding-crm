from onboarding_crm.extensions import db
from flask_login import UserMixin
from datetime import datetime
import json

# ─────────────────────────────────────────────
# 🔹 Модель користувача (менеджер, ментор, ТЛ)
# ─────────────────────────────────────────────
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    tg_nick = db.Column(db.String(150))
    department = db.Column(db.String(150))
    position = db.Column(db.String(100))
    username = db.Column(db.String(150), unique=True)
    password = db.Column(db.String(256))
    role = db.Column(db.String(50))

    added_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    added_by = db.relationship('User', remote_side=[id])

    onboarding_status = db.Column(db.String(100), default='Не розпочато')
    onboarding_step = db.Column(db.Integer, default=0)
    onboarding_step_total = db.Column(db.Integer, default=0)
    onboarding_name = db.Column(db.String(150))
    onboarding_start = db.Column(db.DateTime)
    onboarding_end = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    structure = db.Column(db.JSON)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    steps = db.relationship('OnboardingStep', backref='template', cascade='all, delete-orphan', lazy=True)


# ─────────────────────────────────────────────
# 🔹 Етап шаблону (може бути текстовий або тестовий)
# ─────────────────────────────────────────────
class OnboardingStep(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    template_id = db.Column(db.Integer, db.ForeignKey('onboarding_template.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    order = db.Column(db.Integer)

    step_type = db.Column(db.String(50))  # тип: "text" або "test"
    test = db.relationship('OnboardingTest', uselist=False, backref='step', cascade='all, delete-orphan')


# ─────────────────────────────────────────────
# 🔹 Тест до етапу (опціонально)
# ─────────────────────────────────────────────
class OnboardingTest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    step_id = db.Column(db.Integer, db.ForeignKey('onboarding_step.id'), nullable=False)
    question = db.Column(db.String(255), nullable=False)
    options = db.Column(db.JSON)
    correct_answer = db.Column(db.String(255))


# ─────────────────────────────────────────────
# 🔹 Індивідуальний онбординг для менеджера
# ─────────────────────────────────────────────
class OnboardingInstance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    manager_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    mentor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    structure = db.Column(db.JSON, nullable=False)
    onboarding_step = db.Column(db.Integer, default=0)
    onboarding_step_total = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    manager = db.relationship('User', foreign_keys=[manager_id], backref='manager_onboardings')
    mentor = db.relationship('User', foreign_keys=[mentor_id], backref='mentor_onboardings')


# ─────────────────────────────────────────────
# 🔹 Результати тестів
# ─────────────────────────────────────────────
class TestResult(db.Model):
    __tablename__ = 'test_result'

    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    question = db.Column(db.String(512), nullable=False)            # Текст вопроса
    correct_answer = db.Column(db.String(512), nullable=True)       # Для открытых вопросов можно оставить пустым
    selected_answer = db.Column(db.String(512), nullable=True)      # Ответ менеджера (или ссылка)
    
    # ✅ Теперь можно хранить NULL (None), чтобы различать:
    #   True / False — проверенные тестовые вопросы
    #   None         — открытые вопросы, ожидающие проверки
    is_correct = db.Column(db.Boolean, nullable=True)               
    
    step = db.Column(db.Integer, nullable=True)                     # Номер шага онбординга
    created_at = db.Column(db.DateTime, default=datetime.utcnow)