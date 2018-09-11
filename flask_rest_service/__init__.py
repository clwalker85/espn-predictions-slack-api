import os
import sys
import pprint
import logging
import types
import pytz
from datetime import datetime, time
from flask import Flask, jsonify
from flask.ext import restful
from flask.ext.pymongo import PyMongo
from slackclient import SlackClient

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

MONGO_URL = os.environ.get('MONGODB_URI')
if not MONGO_URL:
    MONGO_URL = "mongodb://localhost:27017/rest";
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

client_id = os.environ.get('SLACK_CLIENT_ID')
client_secret = os.environ.get('SLACK_CLIENT_SECRET')
oauth_scope = os.environ.get('SLACK_BOT_SCOPE')

### LEAGUE CONSTANTS (mostly data we need to abstract away from the business logic)

# get the last inserted row in league_metadata (done by hand in the mlab website)
# TODO - Find a way to fetch some of this through the ESPN API when teams are locked in
# Might have to always manually link an ESPN user to their Slack user
with app.app_context():
    LEAGUE_METADATA = mongo.db.league_metadata.find_one(sort=[('_id', -1)])

LEAGUE_ID = LEAGUE_METADATA['league_id']
LEAGUE_YEAR = LEAGUE_METADATA['year']
# python-ish way to return plucked value in array of dictionaries
LEAGUE_MEMBERS = [m['display_name'] for m in LEAGUE_METADATA['members']]
LEAGUE_USERNAMES = [m['slack_username'] for m in LEAGUE_METADATA['members']]
LEAGUE_USER_IDS = [m['slack_user_id'] for m in LEAGUE_METADATA['members']]

# get the matchup data for the current week
# TODO - Find a way to fetch this through the ESPN API, maybe every time we fetch scores
# Might have to handle playoffs in a special way
with app.app_context():
    MATCHUP_METADATA = mongo.db.matchup_metadata.find_one({ 'year': LEAGUE_YEAR,
        'start_of_week_time': { '$lte': datetime.now() } }, sort=[('week', -1)])

LEAGUE_WEEK = MATCHUP_METADATA['week']
tz_aware_deadline_time = MATCHUP_METADATA['deadline_time']
DEADLINE_TIME = tz_aware_deadline_time.replace(tzinfo=None)
# Tuesday @ 8AM of that week
WEEK_END_TIME = MATCHUP_METADATA['end_of_week_time'].replace(tzinfo=None)
pprint.pprint(WEEK_END_TIME)
pprint.pprint(datetime.now())
MATCHUPS = MATCHUP_METADATA['matchups']
PREDICTION_ELIGIBLE_MEMBERS = [m['team_one'] for m in MATCHUPS] + [m['team_two'] for m in MATCHUPS]

# strftime doesn't provide anything besides zero-padded numbers in formats,
# so it looks like -------------------------------------> "December 23, 2017, at 04:30PM"
# TODO - Use a better date formatter, to try and get ---> "December 23rd, 2017, at 4:30PM"
DEADLINE_STRING = DEADLINE_TIME.strftime('%B %d, %Y, at %I:%M%p')

### GENERAL PURPOSE METHODS (not API related) ###

def post_to_slack(payload):
    slack_token = os.environ['SLACK_API_TOKEN']
    sc = SlackClient(slack_token)

    for user_id in LEAGUE_USER_IDS:
				# uncomment this line to send shit only to Walker
        #if user_id in [ 'U3NE3S6CQ' ]:
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

### SEE BELOW FOR API ENDPOINT DEFINITIONS ###

import flask_rest_service.resources
