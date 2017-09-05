import json
from flask import request, abort, Response
from flask.ext import restful
from flask.ext.restful import reqparse
from flask_rest_service import app, api, mongo
from bson.objectid import ObjectId
import requests
from espnff import League

LEAGUE_ID = 367562
SLACK_VERIFICATION_TOKEN = 'xoxp-125201920852-124479890432-236526482357-4675020c52bc75a98a164e0cd903a683'
WEBHOOK_URL = 'https://hooks.slack.com/services/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'
FAKE_MATCHUPS = [
    ('Freddy versus Joel', 'Freddy', 'Joel'),
    ('Tom versus Alexis', 'Tom', 'Alexis'),
    ('Kevin versus Stan', 'Kevin', 'Stan'),
    ('Todd versus James', 'Todd', 'James'),
    ('Justin versus Mike', 'Justin', 'Mike'),
    ('Renato versus Bryant', 'Renato', 'Bryant'),
    ('Walker versus Cathy', 'Walker', 'Cathy'),
]
LEAGUE_MEMBERS = ['Freddy', 'Joel', 'Tom', 'Alexis', 'Kevin', 'Stan', 'Todd', 'James', 'Justin', 'Mike', 'Renato', 'Bryant', 'Walker', 'Cathy']

def post_to_slack(payload):
    headers = { 'content-type': 'application/json' }
    payload = json.dumps(payload)
    return requests.post(WEBHOOK_URL, headers=headers, data=payload)

def post_text_to_slack(text):
    return post_to_slack({'text': text})

class Root(restful.Resource):
    def get(self):
        #league = League(LEAGUE_ID, 2016),
        return {
            'status': 'OK',
            'mongo': str(mongo.db),
            #'league': league,
            #'scoreboard': league.scoreboard(week=1)
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

        post_text_to_slack(league.scoreboard(week=week))

class Prediction(restful.Resource):
    def post(self):
        #dump = request.headers
        #post_to_slack({
        #    'text': str(vars(dump)),
        #    'channel': '#test_messages'
        #})
        #return ({
        #    'replace_original': false
        #}, 200, None)

class SendPredictionForm(restful.Resource):
    def get(self):
        year = '2017'
        week = '1'

        message = {
            'text': 'Make your predictions for this week''s matchups below:',
            'channel': '#test_messages',
            'attachments': []
        }
        for index, matchup in enumerate(FAKE_MATCHUPS):
            message['attachments'].append({
                'text': matchup[0],
                'attachment_type': 'default',
                'callback_id': year + '-' + week,
                'actions': [
                    {
                        'name': 'winner' + str(index),
                        'text': matchup[1],
                        'type': 'button',
                        'value': matchup[1]
                    },
                    {
                        'name': 'winner' + str(index),
                        'text': matchup[2],
                        'type': 'button',
                        'value': matchup[2]
                    }
                ]
            })

        blowout_dropdown = {
            'text': 'Which matchup will have the biggest blowout?',
            'attachment_type': 'default',
            'callback_id': year + '-' + week,
            'actions': [
                {
                    'name': 'blowout',
                    'text': 'Pick a matchup...',
                    'type': 'select',
                    'options': []
                }
            ]
        }
        for matchup in FAKE_MATCHUPS:
            blowout_dropdown['actions'][0]['options'].append({
                'text': matchup[0],
                'value': matchup[0]
            })
        message['attachments'].append(blowout_dropdown)

        closest_dropdown = {
            'text': 'Which matchup will have the closest score?',
            'attachment_type': 'default',
            'callback_id': year + '-' + week,
            'actions': [
                {
                    'name': 'closest',
                    'text': 'Pick a matchup...',
                    'type': 'select',
                    'options': []
                }
            ]
        }
        for matchup in FAKE_MATCHUPS:
            closest_dropdown['actions'][0]['options'].append({
                'text': matchup[0],
                'value': matchup[0]
            })
        message['attachments'].append(closest_dropdown)

        highest_dropdown = {
            'text': 'Who will be the highest scorer?',
            'attachment_type': 'default',
            'callback_id': year + '-' + week,
            'actions': [
                {
                    'name': 'lowest',
                    'text': 'Pick a team...',
                    'type': 'select',
                    'options': []
                }
            ]
        }
        for team in LEAGUE_MEMBERS:
            highest_dropdown['actions'][0]['options'].append({
                'text': team,
                'value': team
            })
        message['attachments'].append(highest_dropdown)

        lowest_dropdown = {
            'text': 'Who will be the lowest scorer?',
            'attachment_type': 'default',
            'callback_id': year + '-' + week,
            'actions': [
                {
                    'name': 'lowest',
                    'text': 'Pick a team...',
                    'type': 'select',
                    'options': []
                }
            ]
        }
        for team in LEAGUE_MEMBERS:
            lowest_dropdown['actions'][0]['options'].append({
                'text': team,
                'value': team
            })
        message['attachments'].append(lowest_dropdown)

        post_to_slack(message)

        return '';

api.add_resource(Root, '/')
api.add_resource(Scoreboard, '/scoreboard/')
api.add_resource(Prediction, '/prediction/')
api.add_resource(SendPredictionForm, '/prediction/form/')
