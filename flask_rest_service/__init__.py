import os
import sys
import pprint
import logging
import types
import pytz
from datetime import datetime, time, timedelta
from flask import Flask, jsonify
#from flask.ext import restful
import flask_restful as restful
#from flask.ext.pymongo import PyMongo
from flask_pymongo import PyMongo
from slack import WebClient
from dotenv import load_dotenv
from espn_api.football import League

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

client_id = os.environ.get('SLACK_CLIENT_ID')
client_secret = os.environ.get('SLACK_CLIENT_SECRET')
oauth_scope = os.environ.get('SLACK_BOT_SCOPE')
ESPN_SWID = os.environ.get('ESPN_SWID')
ESPN_S2 = os.environ.get('ESPN_S2')

### LEAGUE CONSTANTS (mostly data we need to abstract away from the business logic)

# TODO - Find a way to fetch some of this through the ESPN API when teams are locked in
# Might have to always manually link an ESPN user to their Slack user
with app.app_context():
    LEAGUE_METADATA = mongo.db.league_metadata.find_one(sort=[('year', -1)])

LEAGUE_ID = LEAGUE_METADATA['league_id']
LEAGUE_YEAR = LEAGUE_METADATA['year']
# python-ish way to return plucked value in array of dictionaries
LEAGUE_MEMBERS = [m['display_name'] for m in LEAGUE_METADATA['members']]
LEAGUE_USERNAMES = [m['slack_username'] for m in LEAGUE_METADATA['members']]
LEAGUE_USER_IDS = [m['slack_user_id'] for m in LEAGUE_METADATA['members']]

# get the matchup data for the current week
# IF IT DOESN'T EXIST FOR THIS WEEK, THIS APP WILL COME TO A CRASHING HALT
# TODO - Find a way to fetch this through the ESPN API, maybe every time we fetch scores
# Might have to handle playoffs in a special way
with app.app_context():
    MATCHUP_METADATA = mongo.db.matchup_metadata.find_one({ 'year': LEAGUE_YEAR,
        'start_of_week_time': { '$lte': datetime.now() } }, sort=[('start_of_week_time', -1)])
    LAST_MATCHUP_METADATA = mongo.db.matchup_metadata.find_one({ 'year': LEAGUE_YEAR,
        'end_of_week_time': { '$lte': datetime.now() } }, sort=[('end_of_week_time', -1)])

if not MATCHUP_METADATA:
    next_tuesday_candidate = datetime.today()
    # `1` represents Tuesday
    while next_tuesday_candidate.weekday() != 1:
        next_tuesday_candidate += timedelta(days=1)

    eight_am = time(hour=8)
    start_of_week_time = datetime.combine(next_tuesday_candidate, eight_am)
    end_of_week_time = datetime.combine(start_of_week_time + timedelta(days=7), eight_am)

    eight_twenty_pm = time(hour=20, minute=20)
    deadline_time = datetime.combine(start_of_week_time + timedelta(days=2), eight_twenty_pm)

    player_lookup_by_espn_name = {}
    for p in mongo.db.player_metadata.find():
        if p['espn_owner_name']:
            player_lookup_by_espn_name[p['espn_owner_name']] = p

    matchups = []
    league = League(league_id=int(LEAGUE_ID), year=int(LEAGUE_YEAR), espn_s2=ESPN_S2, swid=ESPN_SWID)
    box_scores = league.box_scores(1)

    # TODO - save these as ints instead
    database_key = { 'year': LEAGUE_YEAR, 'week': '1' }

    for s in box_scores:
        if not hasattr(s.home_team, 'owner') or not hasattr(s.away_team, 'owner'):
            continue

        home_name = player_lookup_by_espn_name[s.home_team.owner]['display_name']
        away_name = player_lookup_by_espn_name[s.away_team.owner]['display_name']

        matchup = {
            'team_one': away_name,
            'team_two': home_name,
            # TODO - insert player IDs as well, for migration away from strings
        }

        matchups.append(matchup)

    record = {
        # TODO - save these as ints instead
        'year': LEAGUE_YEAR,
        'week': '1',
        'matchups': matchups,
        'start_of_week_time': start_of_week_time,
        'deadline_time': deadline_time,
        'end_of_week_time': end_of_week_time,
    }
    # guarantee one record per year/week
    mongo.db.matchup_metadata.update_one(database_key, {
        '$set': record,
    }, upsert=True)

    MATCHUP_METADATA = record

LEAGUE_WEEK = MATCHUP_METADATA['week']
# we won't find the last matchup in week one, so let's just avoid null pointers
if not LAST_MATCHUP_METADATA:
    LAST_MATCHUP_METADATA = MATCHUP_METADATA
LAST_LEAGUE_WEEK = LAST_MATCHUP_METADATA['week']
tz_aware_deadline_time = MATCHUP_METADATA['deadline_time']
DEADLINE_TIME = tz_aware_deadline_time.replace(tzinfo=None)
MATCHUPS = MATCHUP_METADATA['matchups']
PREDICTION_ELIGIBLE_MEMBERS = [m['team_one'] for m in MATCHUPS] + [m['team_two'] for m in MATCHUPS]

# strftime doesn't provide anything besides zero-padded numbers in formats,
# so it looks like -------------------------------------> "December 23, 2017, at 04:30PM"
# TODO - Use a better date formatter, to try and get ---> "December 23rd, 2017, at 4:30PM"
DEADLINE_STRING = DEADLINE_TIME.strftime('%B %d, %Y, at %I:%M%p ')

def refresh_week_constants():
    with app.app_context():
        MATCHUP_METADATA = mongo.db.matchup_metadata.find_one({ 'year': LEAGUE_YEAR,
            'start_of_week_time': { '$lte': datetime.now() } }, sort=[('start_of_week_time', -1)])
        LAST_MATCHUP_METADATA = mongo.db.matchup_metadata.find_one({ 'year': LEAGUE_YEAR,
            'end_of_week_time': { '$lte': datetime.now() } }, sort=[('end_of_week_time', -1)])

    LEAGUE_WEEK = MATCHUP_METADATA['week']
    if not LAST_MATCHUP_METADATA:
        LAST_MATCHUP_METADATA = MATCHUP_METADATA
    LAST_LEAGUE_WEEK = LAST_MATCHUP_METADATA['week']
    tz_aware_deadline_time = MATCHUP_METADATA['deadline_time']
    DEADLINE_TIME = tz_aware_deadline_time.replace(tzinfo=None)
    MATCHUPS = MATCHUP_METADATA['matchups']
    PREDICTION_ELIGIBLE_MEMBERS = [m['team_one'] for m in MATCHUPS] + [m['team_two'] for m in MATCHUPS]
    DEADLINE_STRING = DEADLINE_TIME.strftime('%B %d, %Y, at %I:%M%p ')

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
