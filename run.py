import os

from onboarding_crm import create_app

# register_custom_filters() and Migrate are already wired inside create_app().
app = create_app()

if __name__ == '__main__':
    # Port is configurable (macOS AirPlay Receiver squats on 5000): PORT=5001 python run.py
    app.run(debug=True, port=int(os.environ.get('PORT', 5000)))
