import os
import json
import pprint
import requests
from decimal import Decimal
from datetime import datetime
from espnff import League
from flask import request, abort, Response
from flask.ext import restful
# see __init__.py for these definitions
from flask_rest_service import app, api, mongo, post_to_slack, LEAGUE_ID, LEAGUE_MEMBERS, LEAGUE_USERNAMES, LEAGUE_YEAR, LEAGUE_WEEK, LAST_LEAGUE_WEEK, DEADLINE_STRING, DEADLINE_TIME, MATCHUPS, PREDICTION_ELIGIBLE_MEMBERS

# simple proof of concept that I could get Mongo working in Heroku
@api.route('/')
class Root(restful.Resource):
    def get(self):
        return {
            'status': 'OK',
            'mongo': str(mongo.db),
        }

# TODO - Add a scoreboard command when the ESPN API can be used with our league
# https://github.com/rbarton65/espnff/pull/41
@api.route('/scoreboard/')
class Scoreboard(restful.Resource):
    def post(self):
        # for direct Slack commands, you don't get a payload like an interactive message action,
        # you have to parse the text of the parameters
        text = request.form.get('text', None)
        param = text.split()
        query_type = param[0]

        message = {
            'response_type': 'in_channel',
            'text': '',
            'attachments': []
        }

        #if query_type == 'help':
        #message['attachments'].append({ 'text': prediction_string })


        #league = League(LEAGUE_ID, LEAGUE_YEAR)
        #pprint.pformat(league)
        #pprint.pformat(league.scoreboard())
        return Response("Bernie was here")
