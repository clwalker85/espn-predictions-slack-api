import json
import pprint
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
LEAGUE_MEMBERS = ['Alexis', 'Bryant', 'Cathy', 'Freddy', 'Ian', 'James', 'Joel', 'Justin', 'Kevin', 'Mike', 'Renato', 'Todd', 'Tom', 'Walker']
LEAGUE_YEAR = '2017'
LEAGUE_WEEK = '1'
MATCHUPS = [
    ('Walker versus Renato', 'Walker', 'Renato'),
    ('Bryant versus Mike', 'Bryant', 'Mike'),
    ('Kevin versus Justin', 'Kevin', 'Justin'),
    ('Todd versus Freddy', 'Todd', 'Freddy'),
    ('Tom versus Alexis', 'Tom', 'Alexis'),
    ('James versus Ian', 'James', 'Ian'),
    ('Cathy versus Joel', 'Cathy', 'Joel'),
]

def post_to_slack(payload):
    headers = { 'content-type': 'application/json' }
    payload = json.dumps(payload)
    return requests.post(WEBHOOK_URL, headers=headers, data=payload)

def post_text_to_slack(text):
    return post_to_slack({'text': text})

class Root(restful.Resource):
    def get(self):
        return {
            'status': 'OK',
            'mongo': str(mongo.db),
        }

class Scoreboard(restful.Resource):
    def post(self):
        #league = League(LEAGUE_ID, year)

        #post_text_to_slack(league.scoreboard(week=week))
        return Response()

class Prediction(restful.Resource):
    def post(self):
        payload = json.loads(request.form.get('payload', None))

        username = payload['user']['name']
        year_and_week = payload['callback_id']
        message = payload['original_message']
        actions = payload['actions']

        for attachment in message['attachments']:
            for action in actions:
                for element in attachment['actions']:
                    if element['type'] == 'button' and action['name'] == element['name'] and action['value'] == element['value']:
                        attachment['color'] = 'good'
                        element['style'] = 'primary'

                    if element['type'] == 'button' and action['name'] == element['name'] and action['value'] != element['value']:
                        element['style'] = None

                    if element['type'] == 'select' and action['name'] == element['name']:
                        attachment['color'] = 'good'
                        element['selected_options'] = []
                        for selected in action['selected_options']:
                            for option in element['options']:
                                if option['value'] == selected['value']:
                                    element['selected_options'].append(option)

        ## Slack replaces old prediction form with any immediate response,
        ## so return the form again with any selected buttons styled
        print(message)
        return message

class SendPredictionForm(restful.Resource):
    def get(self):
        message = {
            'text': 'Make your predictions for this week''s matchups below:',
            'channel': '#test_messages',
            'attachments': []
        }
        for index, matchup in enumerate(MATCHUPS):
            message['attachments'].append({
                'text': matchup[0],
                'attachment_type': 'default',
                'callback_id': LEAGUE_YEAR + '-' + LEAGUE_WEEK,
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
            'callback_id': LEAGUE_YEAR + '-' + LEAGUE_WEEK,
            'actions': [
                {
                    'name': 'blowout',
                    'text': 'Pick a matchup...',
                    'type': 'select',
                    'options': []
                }
            ]
        }
        for matchup in MATCHUPS:
            blowout_dropdown['actions'][0]['options'].append({
                'text': matchup[0],
                'value': matchup[0]
            })
        message['attachments'].append(blowout_dropdown)

        closest_dropdown = {
            'text': 'Which matchup will have the closest score?',
            'attachment_type': 'default',
            'callback_id': LEAGUE_YEAR + '-' + LEAGUE_WEEK,
            'actions': [
                {
                    'name': 'closest',
                    'text': 'Pick a matchup...',
                    'type': 'select',
                    'options': []
                }
            ]
        }
        for matchup in MATCHUPS:
            closest_dropdown['actions'][0]['options'].append({
                'text': matchup[0],
                'value': matchup[0]
            })
        message['attachments'].append(closest_dropdown)

        highest_dropdown = {
            'text': 'Who will be the highest scorer?',
            'attachment_type': 'default',
            'callback_id': LEAGUE_YEAR + '-' + LEAGUE_WEEK,
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
            'callback_id': LEAGUE_YEAR + '-' + LEAGUE_WEEK,
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

        return Response()

api.add_resource(Root, '/')
api.add_resource(Scoreboard, '/scoreboard/')
api.add_resource(Prediction, '/prediction/')
api.add_resource(SendPredictionForm, '/prediction/form/')
