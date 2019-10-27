import logging
import json
import pexpect
from os.path import isfile
from pathlib import Path
from time import sleep

from app import app, server
from configuration import conf, mcr, mcq, update_users, update_mc
from flask import abort, jsonify, request
from flask_jwt import jwt_required


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


@app.route("/")
@jwt_required()
def root():
    """
    Show server status
    :return: Actual status of the server
    """
    if server and server.isalive():  # Check is server is online
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
    if not server or not server.isalive():  # Check if the server is offline
        update_properties()  # Update server.properties
        # Start the server
        server = pexpect.spawn("java", ["-Xms"+conf["Server min ram"], "-Xmx"+conf["Server max ram"], "-jar",
                                        conf["Jar server"], "nogui"], cwd=Path(conf["Path"]), echo=False)
        if not isfile(Path(conf["Path"]) / "server.properties"):  # If no server.properties reboot to apply the changes
            # Wait the creation of the properties fle
            while not isfile(Path(conf["Path"]) / "server.properties"):
                sleep(1)
            kill()  # Kill the server
            # Wait for processe full exit
            while server.isalive():
                sleep(1)
            start()  # Start again the server
        # Wait the log file to be archived
        while open(Path(conf["Path"])/"logs"/"latest.log", "r").read() != "":
            sleep(1)
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
    if server and server.isalive():  # Check if server is running
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
    if server and server.isalive():  # Check if the server is running
        server.terminate()  # Kill the process
        return "Ok"
    else:
        abort(400, "Server is not running")


@app.route("/cmd", methods=["POST"])
@jwt_required()
def cmd(command=None):
    """
    Execute a command by stdin on the server
    :param command: The command to execute
    :return: Ok or 400 if server is not running
    """
    if not command:
        try:
            command = request.json["command"]
        except (json.JSONDecodeError, KeyError):
            raise TypeError

    if server and server.isalive():
        server.sendline(command)
        return "Ok"
    else:
        abort(400, "Server is not running")


@app.route("/rcmd", methods=["POST"])
@jwt_required()
def rcmd(command=None):
    """
    Execute a command by Rcon on the server
    :param command: The command to execute
    :return: The result of the command or 400 error if server not running also if Rcon connexion fail
    """
    if not command:
        try:
            command = request.json["command"]
        except (json.JSONDecodeError, KeyError):
            raise TypeError

    if server and server.isalive():  # Check if server is running
        try:  # In case of Rcon connexion fail
            with mcr:  # Open a Rco connexion
                resp = mcr.command(command)  # Send the command
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
    if server and server.isalive():  # Check if server is running
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
    update_users()
    update_mc()
    return jsonify(conf)
