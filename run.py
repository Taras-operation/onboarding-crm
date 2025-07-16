from onboarding_crm import create_app
from onboarding_crm.utils import register_custom_filters

app = create_app()
register_custom_filters(app)  # ✅ Додаємо тут

if __name__ == '__main__':
    app.run(debug=True)

from flask_migrate import Migrate
from onboarding_crm.extensions import db
from onboarding_crm.models import *

migrate = Migrate(app, db)