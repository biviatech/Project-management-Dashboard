from flask import Flask
from flask_login import LoginManager
import os
from dotenv import load_dotenv

load_dotenv()


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'your-secret-key-here'

    # Initialize Flask-Login
    login_manager = LoginManager()
    login_manager.login_view = 'main.login'
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        if not user_id:
            return None
        from flask import session as _session
        from .routes import SimpleUser, get_firebase_user, get_user_role
        cached_role = _session.get('user_role')
        cached_name = _session.get('user_name', '')
        if cached_role:
            return SimpleUser(user_id, name=cached_name, role=cached_role)
        firebase_user = get_firebase_user(user_id) or {}
        role = get_user_role(user_id)
        name = firebase_user.get('name') or _session.get('user_name', '')
        _session['user_name'] = name
        _session['user_role'] = role
        return SimpleUser(user_id, name=name, role=role)

    # Register blueprints
    from .routes import main
    app.register_blueprint(main)

    return app
