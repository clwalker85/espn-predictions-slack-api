import os
import sys
import logging
from datetime import datetime
from flask import Flask, jsonify
from flask.ext import restful
from flask.ext.pymongo import PyMongo
from flask import make_response
from slackclient import SlackClient

MONGO_URL = os.environ.get('MONGODB_URI')
if not MONGO_URL:
    MONGO_URL = "mongodb://localhost:27017/rest";

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
        return wrapper

api.route = types.MethodType(api_route, api)

client_id = os.environ.get('SLACK_CLIENT_ID')
client_secret = os.environ.get('SLACK_CLIENT_SECRET')
oauth_scope = os.environ.get('SLACK_BOT_SCOPE')

# TODO - replace this shit with a database table
LEAGUE_ID = 367562
LEAGUE_MEMBERS = ['Alexis', 'Bryant', 'Cathy', 'Freddy', 'Ian', 'James', 'Joel', 'Justin', 'Kevin', 'Mike', 'Renato', 'Todd', 'Tom', 'Walker']
LEAGUE_USERNAMES = ['alexis', 'bernie', 'wildcougar', 'freddy', 'imcguigan', 'jtylee', 'hotdogs-sleep', 'jutsman', 'kevin', 'mikejetmcloughlin', 'ropacak', 'lutedog', 'tom', 'clwalker']
# same order as arrays above
LEAGUE_USER_IDS = ['U3P2770FK', 'U3P6D7PT7', 'U3P6LPVLM', 'U3P3NU4E6', 'U6T9Y84LS', 'U5C50S29H', 'U5RV1SGSE', 'U5TQ9NKEX', 'U3P4HLXD0', 'U5SF98KMX', 'U4L7RTJ30', 'U3PHKK00L', 'U3NEWLZFS', 'U3NE3S6CQ']
LEAGUE_YEAR = '2017'
# MODIFY THIS SHIT BELOW UNTIL WE CAN AUTOMATE THIS THROUGH ESPN API
LEAGUE_WEEK = '16'
DEADLINE_STRING = 'December 23rd, 2017, at 4:30PM'
# UTC version of time above - https://www.worldtimebuddy.com/
DEADLINE_TIME = datetime.strptime('December 23 2017 09:30PM', '%B %d %Y %I:%M%p')
# UTC version of Tuesday @ 8AM of that week; remember leading zeroes in days!
WEEK_END_TIME = datetime.strptime('December 26 2017 01:00PM', '%B %d %Y %I:%M%p')
MATCHUPS = [
    ('Bryant versus Todd', 'Bryant', 'Todd'),
    ('Justin versus Walker', 'Justin', 'Walker'),
    ('Renato versus Joel', 'Renato', 'Joel'),
    ('Alexis versus Kevin', 'Alexis', 'Kevin'),
    ('Freddy versus Tom', 'Freddy', 'Tom'),
    ('Ian versus Mike', 'Ian', 'Mike'),
    ('Cathy versus James', 'Cathy', 'James'),
]
# END TODO - replace this shit with a database table

def post_to_slack(payload):
    slack_token = os.environ['SLACK_API_TOKEN']
    sc = SlackClient(slack_token)

    for user_id in LEAGUE_USER_IDS:
				# uncomment this line to send shit only to Walker
        #if user_id not in [ 'U3NE3S6CQ' ]:
            channel = sc.api_call('im.open', user=user_id)

            if 'channel' in channel:
                channel = channel['channel']

            sc.api_call("chat.postMessage",
                channel=channel['id'],
                text=payload['text'],
                attachments=payload['attachments'],
                as_user=False
            )
    return

# NOT IN USE, but here in case it's needed
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
