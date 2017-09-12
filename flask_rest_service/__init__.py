import os
from flask import Flask
from flask.ext import restful
from flask.ext.pymongo import PyMongo
from flask import make_response
from bson.json_util import dumps
from slackclient import SlackClient

MONGO_URL = os.environ.get('MONGODB_URI')
if not MONGO_URL:
    MONGO_URL = "mongodb://localhost:27017/rest";

app = Flask(__name__)

app.config['MONGO_URI'] = MONGO_URL
mongo = PyMongo(app)

def output_json(obj, code, headers=None):
    resp = make_response(dumps(obj), code)
    resp.headers.extend(headers or {})
    return resp

DEFAULT_REPRESENTATIONS = {'application/json': output_json }
api = restful.Api(app)
api.representations = DEFAULT_REPRESENTATIONS

client_id = os.environ.get('SLACK_CLIENT_ID')
client_secret = os.environ.get('SLACK_CLIENT_SECRET')
oauth_scope = os.environ.get('SLACK_BOT_SCOPE')

@app.route('/auth', methods=['GET', 'POST'])
def auth():
    auth_code = request.args['code']
    sc = SlackClient('')
    auth_response = sc.api_call(
        'oauth.access',
        client_id=client_id,
        client_secret=client_secret,
        code=auth_code
    )

    os.environ['SLACK_USER_TOKEN'] = auth_response['access_token']
    os.environ['SLACK_BOT_TOKEN'] = auth_response['bot']['bot_access_token']

import flask_rest_service.resources
