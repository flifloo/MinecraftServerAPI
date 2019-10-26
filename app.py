import json
import logging
import subprocess
from os import urandom
from os.path import isfile
from pathlib import Path
from time import sleep

from flask import Flask, abort, jsonify, request
from flask_jwt import JWT, jwt_required
from mcrcon import MCRcon
from mcstatus import MinecraftServer
from werkzeug.security import check_password_hash, generate_password_hash


# Create default configuration file
if not isfile("config.json"):
    logging.info("No config file, creating nwe one")
    conf = {
        "Key": str(urandom(24)),
        "Users": {"admin": generate_password_hash("admin")},
        "Path": "",
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
    with open(Path(conf["Path"])/"eula.txt") as elua:
        elua.write("eula=true")


# Configuration of flask
class Config(object):
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


# Convert user form config to User object
# TODO: Support config change
users = list()
for i, u in enumerate(conf["Users"]):
    users.append(User(i+1, u, conf["Users"][u]))
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


def update_properties():
    """
    Update server.properties with configuration arguments
    """
    if isfile(Path(conf["Path"]) / "server.properties"):  # Check if properties file exist
        logging.info("Check server.properties")
        # Get the content of the file
        with open(Path(conf["Path"]) / "server.properties", "r") as properties_file:
            properties = properties_file.read()
        # Default configuration
        properties_conf = {"enable-rcon": "true", "enable-query": "true", "rcon.port": conf["Rcon port"],
                           "query.port": conf["Query port"], "rcon.password": conf["Rcon passwd"]}
        properties_conf.update(conf["Properties"])  # Add of extra configuration
        for c in properties_conf:  # For every configuration
            # Get the start, the middle (=) and the end of the configuration
            s = properties.find(c)
            m = properties.find("=", s)
            e = properties.find("\n", m)
            if properties[s:m] == c and properties[m + 1:e] != properties_conf[c]:  # Check if configurations match
                logging.info(f"Change {c} to {properties_conf[c]}")
                properties = properties.replace(properties[s:e], f"{c}={properties_conf[c]}")  # Update configuration
        # Save configuration changes
        with open(Path(conf["Path"]) / "server.properties", "w") as properties_file:
            properties_file.write(properties)


# Setup of globals variables
app = Flask(__name__)  # Setup Flask's app
app.config.from_object(Config)  # Import Flask configuration
# TODO: support config change
mcr = MCRcon(conf["Server ip"], conf["Rcon passwd"], conf["Rcon port"])  # Setup Rcon
mcq = MinecraftServer(conf["Server ip"], conf["Query port"])  # Setup Query
jwt = JWT(app, authenticate, identity)  # Setup JWT
server = None  # Init server


@app.route("/")
@jwt_required()
def root():
    """
    Show server status
    :return: Actual status of the server
    """
    if server and server.poll() is None:  # Check is server is online
        try:  # In case of connexion errors
            status = mcq.status()
            query = mcq.query()
            return f"The server has {status.players.online} players and replied in {status.latency} ms"\
                   + "\n Online players: " + ", ".join(query.players.names)
        except OSError:
            abort(400, "Server did not respond")
    else:
        return "Server is offline"


@app.route("/start")
@jwt_required()
def start():
    """
    Start the server
    :return: Ok if everything is fine, 400 error f server already running
    """
    global server  # Get the global value for reallocation
    if not server or server.poll() is not None:  # Check if the server is offline
        update_properties()  # Update server.properties
        # Start the server
        server = subprocess.Popen(["java", "-Xms"+conf["Server min ram"], "-Xmx"+conf["Server max ram"], "-jar",
                                   conf["Jar server"], "nogui"], stdout=subprocess.PIPE, cwd=Path(conf["Path"]))
        if not isfile(Path(conf["Path"]) / "server.properties"):  # If no server.properties reboot to apply the changes
            # Wait the creation of the properties fle
            while not isfile(Path(conf["Path"]) / "server.properties"):
                sleep(1)
            kill()  # Kill the server because no Rcon connection
            # Wait for subprocesse full exit
            while server.poll() is None:
                sleep(1)
            start()  # Start again the server
        return "Ok"
    else:
        abort(400, "Server is running")


@app.route("/stop")
@jwt_required()
def stop():
    """
    Stop the server
    :return: The result of the /stop command or 400 error if server is not running
    """
    if server and server.poll() is None:  # Check if server is running
        return cmd("/stop")  # Launch /stop command
    else:
        abort(400, "Server is not running")


@app.route("/kill")
@jwt_required()
def kill():
    """
    Kill the server
    :return: Ok or 400 if the server is not running
    """
    if server and server.poll() is None:  # Check if the server is running
        server.kill()  # Kill the subprocess
        return "Ok"
    else:
        abort(400, "Server is not running")


@app.route("/cmd/<cmd>")
@jwt_required()
def cmd(cmd):
    """
    Execute a command by Rcon on the server
    :param cmd: The command to execute
    :return: The result of the command or 400 error if server not running also if Rcon connexion fail
    """
    if server and server.poll() is None:  # Check if server is running
        try:  # In case of Rcon connexion fail
            with mcr:  # Open a Rco connexion
                resp = mcr.command(cmd)  # Send the command
        except (TimeoutError, ConnectionRefusedError):
            abort(400, "Server did not respond")
        else:
            return str(resp)
    else:
        abort(400, "Server is not running")


@app.route("/logs")
@jwt_required()
def logs():
    """
    Get the server logs
    :return: Server last logs or 400 error if server is not running
    """
    if server and server.poll() is None:  # Check if server is running
        return open(Path(conf["Path"])/"logs"/"latest.log", "r").read()  # Send the content of the server logs
    else:
        abort(400, "Server is not running")


@app.route("/config", methods=["GET"])
@jwt_required()
def get_config():
    """
    Get configuration
    :return: The Json configuration
    """
    return jsonify(conf)


@app.route("/config", methods=["PUT"])
@jwt_required()
def update_config():
    """
    Update the configuration
    :return: The updated Json configuration
    """
    for p in request.json:  # For every entry on the request
        if p in conf:  # Check if it match wth the configuration
            conf[p] = request.json[p]  # Update the configuration
    # Save configuration changes
    with open("config.json", "w") as conf_file:
        json.dump(conf, conf_file)
    return jsonify(conf)


# Start of the program
if __name__ == "__main__":
    app.run(ssl_context="adhoc")
