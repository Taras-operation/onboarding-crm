from flask import Flask
from onboarding_crm.extensions import db, login_manager, migrate  # ✅ добавляем migrate
from onboarding_crm.routes import bp
from onboarding_crm.models import User
from onboarding_crm.utils import register_custom_filters
import os


def create_app():
    app = Flask(__name__)
    app.jinja_env.cache = {}
    app.config['SECRET_KEY'] = 'secret-key-goes-here'

    # 📌 Если есть DATABASE_URL, используем PostgreSQL
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    else:
        basedir = os.path.abspath(os.path.dirname(__file__))
        app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(basedir, '../instance/onboarding.db')}"

    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # ✅ подключаем базы и миграции
    db.init_app(app)
    migrate.init_app(app, db)  # <── вот эта строка добавляет поддержку `flask db migrate`
    
    login_manager.init_app(app)
    login_manager.login_view = 'login'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    app.register_blueprint(bp)
    register_custom_filters(app)

    return app