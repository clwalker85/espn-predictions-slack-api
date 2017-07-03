import json
from flask import request, abort
from flask.ext import restful
from flask.ext.restful import reqparse
from flask_rest_service import app, api, mongo
from bson.objectid import ObjectId
import requests
from espnff import League

LEAGUE_ID = 367562
WEBHOOK_URL = 'https://hooks.slack.com/services/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'

def post_to_slack(text):
    headers = { 'content-type': 'application/json' }
    payload = json.dumps({
        'text': text
    })
    return requests.post(WEBHOOK_URL, headers=headers, data=payload)

class Root(restful.Resource):
    def get(self):
        league = League(LEAGUE_ID, 2016),
        return {
            'status': 'OK',
            'mongo': str(mongo.db),
            'league': league,
            'scoreboard': league.scoreboard(week=1)
        }

class Scoreboard(restful.Resource):
    def post(self):
        args = self.parser.parse_args()
        year = 2017

        if args['year']:
            year = args['year']

        if args['week']:
            week = args['week']

        league = League(LEAGUE_ID, year)

        post_to_slack(league.scoreboard(week=week))

api.add_resource(Root, '/')
api.add_resource(Scoreboard, '/scoreboard/')
