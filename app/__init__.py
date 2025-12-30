
import os
from flask import Flask
from flask_pymongo import PyMongo
from flask_login import LoginManager
from dotenv import load_dotenv

mongo = PyMongo()
login_manager = LoginManager()

def create_app():
    load_dotenv()

    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    app.config["MONGO_URI"] = os.getenv("MONGO_URI")

    mongo.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = "main.login"  # blueprint endpoint

    # routes blueprint
    from .routes import main_bp
    app.register_blueprint(main_bp)

    return app
