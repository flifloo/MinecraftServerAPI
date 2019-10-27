from flask import Flask
from flask_jwt import JWT
from configuration import FlaskConfig, authenticate, identity, update_mc, update_users

app = Flask(__name__)  # Setup Flask's app
app.config.from_object(FlaskConfig)  # Import Flask configuration
jwt = JWT(app, authenticate, identity)  # Setup JWT
server = None  # Init server
update_mc()
update_users()

from app import routes
