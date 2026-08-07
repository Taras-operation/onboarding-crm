from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate  # ✅ ДОБАВЬ ЭТО
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()  # ✅ ДОБАВЬ ЭТО
# Rate limiter keyed by client IP (behind Render's proxy — see ProxyFix in create_app).
limiter = Limiter(key_func=get_remote_address, default_limits=[])
