from flask import Flask
from onboarding_crm.extensions import db, login_manager, migrate  # ✅ уже есть
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

    # 📌 2. Конфіг БД
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    else:
        basedir = os.path.abspath(os.path.dirname(__file__))
        app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(basedir, '../instance/onboarding.db')}"

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # ✅ 3. Ініціалізація всіх розширень
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = 'main.login'

    # ✅ 4. Підключаємо CSRFProtect до всього додатку
    csrf.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # ✅ 5. Реєстрація blueprint’ів та фільтрів
    app.register_blueprint(bp)
    register_custom_filters(app)

    return app