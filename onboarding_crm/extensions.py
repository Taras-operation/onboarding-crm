from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate  # ✅ ДОБАВЬ ЭТО

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()  # ✅ ДОБАВЬ ЭТО