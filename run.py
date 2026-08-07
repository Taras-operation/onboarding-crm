from onboarding_crm import create_app

# register_custom_filters() and Migrate are already wired inside create_app().
app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
