from datetime import timedelta

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from onboarding_crm.extensions import db, login_manager, migrate, limiter  # ✅ уже есть
from onboarding_crm.routes import bp
from onboarding_crm.models import User
from onboarding_crm.utils import register_custom_filters
from flask_wtf import CSRFProtect  # 🧩 додай це
import os

try:
    from dotenv import load_dotenv
    load_dotenv()  # read .env for local dev; no-op if the file is absent
except ImportError:
    pass

# 🧩 1. Ініціалізуємо CSRFProtect (глобально)
csrf = CSRFProtect()


def create_app():
    app = Flask(__name__)
    app.jinja_env.cache = {}

    # SECRET_KEY must come from the environment. No fallback on purpose: a missing
    # key fails startup loudly instead of silently signing sessions with a known value.
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        raise RuntimeError('SECRET_KEY is not set')
    app.config['SECRET_KEY'] = secret_key
    app.config['WTF_CSRF_TIME_LIMIT'] = None

    # Session cookie hardening. SECURE defaults to on; set SESSION_COOKIE_SECURE=false in
    # .env for local http dev (otherwise the browser won't send the cookie over http).
    _secure = os.environ.get('SESSION_COOKIE_SECURE', 'true').lower() not in ('0', 'false', 'no')
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=_secure,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    )

    # Behind Render's proxy the real client IP is in X-Forwarded-For — trust one hop so
    # the rate limiter keys on the actual client, not the proxy.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    # 📌 2. Конфіг БД
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    else:
        basedir = os.path.abspath(os.path.dirname(__file__))
        app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(basedir, '../instance/onboarding.db')}"

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Велика форма збереження шаблону: кожен блок/сабблок/тест/відповідь — окреме поле
    # одного urlencoded-POST. Дефолти Werkzeug 3.1 ріжуть форму на 500 КБ у памʼяті та
    # 1000 полів — шаблон на 8–15 тем це перевищує → 413 Request Entity Too Large
    # («The data value transmitted exceeds the capacity limit»). Піднімаємо ліміти із
    # запасом (форма текстова; файли-вкладення вантажаться окремим AJAX-ендпоінтом).
    app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024    # 25 МБ на все тіло запиту
    app.config['MAX_FORM_MEMORY_SIZE'] = 25 * 1024 * 1024  # 25 МБ нефайлових полів форми
    app.config['MAX_FORM_PARTS'] = 20000                   # багато полів у великому шаблоні

    # ✅ 3. Ініціалізація всіх розширень
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'main.login'
    limiter.init_app(app)

    # ✅ 4. Підключаємо CSRFProtect до всього додатку
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ✅ 5. Реєстрація blueprint’ів та фільтрів
    app.register_blueprint(bp)
    register_custom_filters(app)

    return app