import os
import sys
import pprint
import logging
import types
import pytz
from datetime import datetime, time, timedelta
from flask import Flask, jsonify
import flask_restful as restful
from flask_pymongo import PyMongo
from slack import WebClient
from dotenv import load_dotenv
from espn_api.football import League
from facades.metadata import Metadata

load_dotenv()

### APP CONFIG AND SETUP (set it and forget it, nothing to do with business logic)

# see this for the example:
# https://github.com/jwatson/simple-flask-stacktrace/blob/master/server.py
app = Flask(__name__)
app.debug = True
app.logger.setLevel(logging.DEBUG)
del app.logger.handlers[:]
handler = logging.StreamHandler(stream=sys.stdout)
handler.setLevel(logging.DEBUG)
handler.formatter = logging.Formatter(
    fmt=u"%(asctime)s level=%(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
app.logger.addHandler(handler)

MONGO_URL = os.environ.get('MONGOATLASDB_URI')
if not MONGO_URL:
    MONGO_URL = "mongodb://localhost:27017/rest"
app.config['MONGO_URI'] = MONGO_URL
mongo = PyMongo(app)
api = restful.Api(app)

@api.representation('application/json')
def output_json(obj, code, headers=None):
    return jsonify(obj)

# support api.route decorators like the regular flask object
# http://flask.pocoo.org/snippets/129/
def api_route(self, *args, **kwargs):
    def wrapper(cls):
        self.add_resource(cls, *args, **kwargs)
        return cls
    return wrapper
api.route = types.MethodType(api_route, api)

### LEAGUE CONSTANTS (mostly data we need to abstract away from the business logic)

metadata = Metadata(app, mongo)

### GENERAL PURPOSE METHODS (not API related) ###

# requires 'text' (string) and 'attachments' (JSON) to be defined in the payload
def post_to_slack(payload):
    slack_token = os.environ['SLACK_API_TOKEN']
    sc = WebClient(token=slack_token)

    for user_id in LEAGUE_USER_IDS:
	# uncomment this line to send messages only to Walker
        #if user_id in [ 'U3NE3S6CQ' ]:
            channel = sc.conversations_open(users=user_id)
            # unwrap channel information
            channel = channel['channel']

            sc.chat_postMessage(
                channel=channel['id'],
                text=payload['text'],
                attachments=payload['attachments'],
                as_user=False
            )

# requires 'trigger_id' (string) and 'dialog' (JSON) to be defined in the payload
def open_dialog(payload):
    slack_token = os.environ['SLACK_API_TOKEN']
    sc = WebClient(token=slack_token)

    sc.dialog_open(
        trigger_id=payload['trigger_id'],
        dialog=payload['dialog']
    )

# requires 'user_id', 'message_ts', 'text' (all strings),
# and 'attachments' (JSON) to be defined in the payload
def update_message(payload):
    slack_token = os.environ['SLACK_API_TOKEN']
    sc = WebClient(token=slack_token)

    channel = sc.conversations_open(users=payload['user_id'])
    channel = channel['channel']

    sc.chat_update(
        channel=channel['id'],
        ts=payload['message_ts'],
        text=payload['text'],
        attachments=payload['attachments']
    )

### SEE BELOW FOR API ENDPOINT DEFINITIONS ###

import flask_rest_service.predictions
import flask_rest_service.scoreboard
import flask_rest_service.history
