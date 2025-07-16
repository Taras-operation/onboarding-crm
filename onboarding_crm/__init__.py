from flask import Flask
from onboarding_crm.extensions import db, login_manager
from onboarding_crm.routes import bp
from onboarding_crm.models import User
from onboarding_crm.utils import register_custom_filters  # 🔄 імпортуємо

import os

def create_app():
    app = Flask(__name__)
    app.jinja_env.cache = {}  # 🔄 очищення кешу шаблонів
    app.config['SECRET_KEY'] = 'secret-key-goes-here'

    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(basedir, '../instance/onboarding.db')}"

    db.init_app(app)
    login_manager.init_app(app)

    login_manager.login_view = 'login'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    app.register_blueprint(bp)

    # ✅ Реєстрація кастомного Jinja2 фільтра
    register_custom_filters(app)

    return app