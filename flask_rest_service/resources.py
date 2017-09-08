import json
import pprint
import requests
from decimal import Decimal
from datetime import datetime
from espnff import League
from flask import request, abort, Response
from flask.ext import restful
from flask_rest_service import app, api, mongo

LEAGUE_ID = 367562
LEAGUE_MEMBERS = ['Alexis', 'Bryant', 'Cathy', 'Freddy', 'Ian', 'James', 'Joel', 'Justin', 'Kevin', 'Mike', 'Renato', 'Todd', 'Tom', 'Walker']
WEBHOOK_URLS = [
    # Freddy
    'https://hooks.slack.com/services/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'
]
LEAGUE_YEAR = '2017'
LEAGUE_WEEK = '1'
DEADLINE_STRING = 'September 7th, 2017, at 08:30PM'
DEADLINE_TIME = datetime.strptime('September 08 2017 12:30AM', '%B %d %Y %I:%M%p')
MATCHUPS = [
    ('Walker versus Renato', 'Walker', 'Renato'),
    ('Bryant versus Mike', 'Bryant', 'Mike'),
    ('Kevin versus Justin', 'Kevin', 'Justin'),
    ('Todd versus Freddy', 'Todd', 'Freddy'),
    ('Tom versus Alexis', 'Tom', 'Alexis'),
    ('James versus Ian', 'James', 'Ian'),
    ('Cathy versus Joel', 'Cathy', 'Joel'),
]

def post_to_slack(url, payload):
    headers = { 'content-type': 'application/json' }
    payload = json.dumps(payload)
    return requests.post(url, headers=headers, data=payload)

class Root(restful.Resource):
    def get(self):
        return {
            'status': 'OK',
            'mongo': str(mongo.db),
        }

class Scoreboard(restful.Resource):
    def post(self):
        #league = League(LEAGUE_ID, year)
        #league.scoreboard(week=week)
        return Response()

class PredictionSubmissions(restful.Resource):
    def post(self):
        if datetime.now() < DEADLINE_TIME:
            return Response()

        year_and_week = LEAGUE_YEAR + '-' + LEAGUE_WEEK
        message = {
            'response_type': 'in_channel',
            'text': 'Predictions submitted for week ' + LEAGUE_WEEK + ' of ' + LEAGUE_YEAR + ':',
            'attachments': []
        }

        for prediction in mongo.db.predictions.find({ 'year_and_week': year_and_week }):
            username = prediction['username']
            prediction_string = username + ' Winners: '
            winners_string = ''
            matchups_string = ''

            for attachment in prediction['message']['attachments']:
                for action in attachment['actions']:
                    if action['type'] == 'button' and action['style'] == 'primary':
                        winners_string += action['text'] + ', '
                        
                    if action['type'] == 'select' and 'selected_options' in action:
                        pprint.pformat(action)
                        for selected in action['selected_options']:
                            pprint.pformat(selected)
                            matchups_string += attachment['text'] + ': ' + selected['text'] + '\n'

            prediction_string += winners_string.rstrip(', ') + '\n' + matchups_string

            score_prediction = mongo.db.score_predictions.find_one({ 'username': username, 'year_and_week': year_and_week })
            prediction_string += 'Highest Score: ' + score_prediction['high_score'] + '\n'
            prediction_string += 'Lowest Score: ' + score_prediction['low_score']

            message['attachments'].append({ 'text': prediction_string })

        return message

class ScorePrediction(restful.Resource):
    def post(self):
        if datetime.now() > DEADLINE_TIME:
            return 'Prediction not saved for week ' + LEAGUE_WEEK + '. Deadline of ' + DEADLINE_STRING + ' has passed.'

        text = request.form.get('text', None)
        username = request.form.get('user_name', None)
        year_and_week = LEAGUE_YEAR + '-' + LEAGUE_WEEK
        database_key = { 'username': username, 'year_and_week': year_and_week }
        param = text.split()

        if len(param) < 2:
            return 'Prediction not saved for week ' + LEAGUE_WEEK + '. Type in two numbers to the score-prediction command for highest and lowest score next time.'

        try:
            first_score = Decimal(param[0])
            second_score = Decimal(param[1])
            high_score = param[0]
            low_score = param[1]

            if first_score < second_score:
                high_score = param[1]
                low_score = param[0]

            mongo.db.score_predictions.update(database_key, {
                '$set': {
                    'high_score': high_score,
                    'low_score': low_score
                },
            }, upsert=True, multi=False)

            return 'Prediction successfully saved for week ' + LEAGUE_WEEK + '! High score: ' + high_score + ', low score: ' + low_score
        except:
            return 'Prediction not saved for week ' + LEAGUE_WEEK + '. Type in valid decimal numbers next time.'

        return 'Prediction not saved for week ' + LEAGUE_WEEK + '.'

class Prediction(restful.Resource):
    def post(self):
        if datetime.now() > DEADLINE_TIME:
            return Response()

        payload = json.loads(request.form.get('payload', None))

        username = payload['user']['name']
        year_and_week = payload['callback_id']
        database_key = { 'username': username, 'year_and_week': year_and_week }
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

        mongo.db.predictions.update(database_key, {
            '$set': {
                'message': message
            },
        }, upsert=True, multi=False)

        ## Slack replaces old prediction form with any immediate response,
        ## so return the form again with any selected buttons styled
        return message

class SendPredictionForm(restful.Resource):
    def get(self):
        message = {
            'text': 'Make your predictions for this week''s matchups below by ' + DEADLINE_STRING + ':',
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
                    'name': 'highest',
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

        for url in WEBHOOK_URLS:
            post_to_slack(url, message)

        return Response()

api.add_resource(Root, '/')
api.add_resource(Scoreboard, '/scoreboard/')
api.add_resource(Prediction, '/prediction/')
api.add_resource(ScorePrediction, '/prediction/score/')
api.add_resource(SendPredictionForm, '/prediction/form/')
api.add_resource(PredictionSubmissions, '/prediction/submissions/')
