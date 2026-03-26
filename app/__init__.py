
from flask import Flask
import os

def create_app(config_name):
    app = Flask(__name__, 
                template_folder='../templates',
                static_folder='../static')
    
    app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET')
    if not app.config['SECRET_KEY']:
        raise ValueError("FLASK_SECRET environment variable not set.")

    # Register blueprints
    from .employee_routes import employee_bp
    from .manager_routes import manager_bp
    
    if config_name == 'employee':
        app.register_blueprint(employee_bp)
    elif config_name == 'manager':
        app.register_blueprint(manager_bp, url_prefix='/admin')

    return app
