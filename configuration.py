import json
import logging
from os import urandom
from os.path import isfile
from pathlib import Path

from mcrcon import MCRcon
from mcstatus import MinecraftServer
from werkzeug.security import check_password_hash, generate_password_hash


# Create default configuration file
if not isfile("config.json"):
    logging.info("No config file, creating nwe one")
    conf = {
        "Key": str(urandom(24)),
        "Users": {"admin": generate_password_hash("admin")},
        "Path": "server",
        "Jar server": "server.jar",
        "Server min ram": "1024M",
        "Server max ram": "1024M",
        "Server ip": "127.0.0.1",
        "Rcon port": 25575,
        "Rcon passwd": "admin",
        "Query port": 25565,
        "Properties": {}
    }
    with open("config.json", "w") as conf_file:
        json.dump(conf, conf_file)

# Load configuration file
with open("config.json", "r") as conf_file:
    logging.info("Loading configurations")
    conf = json.load(conf_file)

# Check s server jar exist
if not isfile(Path(conf["Path"])/conf["Jar server"]):
    logging.warning("No server jar found !")
    exit()
# Enable elua by default
if not isfile(Path(conf["Path"])/"eula.txt"):
    logging.info("No elua.txt, creating new one")
    with open(Path(conf["Path"])/"eula.txt", "w") as elua:
        elua.write("eula=true")


mcr = None  # Setup Rcon
mcq = None  # Setup Query


def update_mc():
    global mcr, mcq
    mcr = MCRcon(conf["Server ip"], conf["Rcon passwd"], conf["Rcon port"])
    mcq = MinecraftServer(conf["Server ip"], conf["Query port"])


# Configuration of flask
class FlaskConfig(object):
    SECRET_KEY = conf["Key"]
    JWT_AUTH_USERNAME_KEY = "username"


# User object for JWT
class User(object):
    def __init__(self, id, username, password):
        self.id = id
        self.username = username
        self.password = password

    def __str__(self):
        return "User(id='%s')" % self.id


# Users variables init
users = list()
username_table = dict()
userid_table = dict()


def update_users():
    """
    Convert user from config to user object and put in users variables
    """
    global users, username_table, userid_table
    users = [User(i + 1, u, conf["Users"][u]) for i, u in enumerate(conf["Users"])]
    username_table = {u.username: u for u in users}
    userid_table = {u.id: u for u in users}


def authenticate(username, password):
    """
    Authentication for JWT
    :param username: User's username (str)
    :param password: User's password
    :return: User's object if correct username and password
    """
    user = username_table.get(username, None)
    if user and check_password_hash(user.password, password):
        return user


def identity(payload):
    """
    Get identity for JWT
    :param payload: JWT payload
    :return: User's object
    """
    user_id = payload["identity"]
    return userid_table.get(user_id, None)
