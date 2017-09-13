import os
import json
import pprint
import requests
from decimal import Decimal
from datetime import datetime
from espnff import League
from flask import request, abort, Response
from flask.ext import restful
from flask_rest_service import app, api, mongo
from slackclient import SlackClient

LEAGUE_ID = 367562
LEAGUE_MEMBERS = ['Alexis', 'Bryant', 'Cathy', 'Freddy', 'Ian', 'James', 'Joel', 'Justin', 'Kevin', 'Mike', 'Renato', 'Todd', 'Tom', 'Walker']
LEAGUE_USERNAMES = ['alexis', 'bernie', 'wildcougar', 'freddy', 'imcguigan', 'jtylee', 'hotdogs-sleep', 'jutsman', 'kevin', 'mikejetmcloughlin', 'ropacak', 'lutedog', 'tom', 'clwalker']
LEAGUE_DM_CHANNEL_IDS = ['D3PRFLH2S']
LEAGUE_YEAR = '2017'
LEAGUE_WEEK = '2'
DEADLINE_STRING = 'September 14th, 2017, at 08:25PM'
# UTC version of time above - https://www.worldtimebuddy.com/
DEADLINE_TIME = datetime.strptime('September 15 2017 12:25AM', '%B %d %Y %I:%M%p')
# UTC version of Tuesday @ 8AM of that week
WEEK_END_TIME = datetime.strptime('September 19 2017 12:00PM', '%B %d %Y %I:%M%p')
MATCHUPS = [
    ('Alexis versus Walker', 'Alexis', 'Walker'),
    ('Kevin versus Bryant', 'Kevin', 'Bryant'),
    ('Mike versus Todd', 'Mike', 'Todd'),
    ('Justin versus Tom', 'Justin', 'Tom'),
    ('Freddy versus James', 'Freddy', 'James'),
    ('Ian versus Cathy', 'Ian', 'Cathy'),
    ('Renato versus Joel', 'Renato', 'Joel'),
]

def post_to_slack(payload):
    slack_token = os.environ['SLACK_API_TOKEN']
    sc = SlackClient(slack_token)

    user_list = sc.api_call('users.list', presence=False)
    
    if 'members' in user_list:
        for user in user_list['members']:
            if user['name'] in LEAGUE_USERNAMES:
                channel = sc.api_call('im.open', user=user['id'])
                print(user['name'])
                print(user['id'])

                if 'channel' in channel:
                    channel = channel['channel']
                print(channel['id'])

#            sc.api_call("chat.postMessage",
#                channel=channel['id'],
#                text=payload['text'],
#                attachments=payload['attachments'],
#                as_user=False
#            )
    return

class Root(restful.Resource):
    def get(self):
        return {
            'status': 'OK',
            'mongo': str(mongo.db),
        }

class Scoreboard(restful.Resource):
    def post(self):
        #league = League(LEAGUE_ID, LEAGUE_YEAR)
        #pprint.pformat(league)
        #pprint.pformat(league.scoreboard())
        return Response()

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
            'fallback': 'Blowout',
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
            'fallback': 'Closest',
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
            'fallback': 'Highest',
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
            'fallback': 'Lowest',
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
            prediction_string = username + ' picks: '
            winners_string, matchups_string = '', ''

            score_prediction = mongo.db.score_predictions.find_one({ 'username': username, 'year_and_week': year_and_week })

            for attachment in prediction['message']['attachments']:
                for action in attachment['actions']:
                    if action['type'] == 'button' and action['style'] == 'primary':
                        winners_string += action['text'] + ', '
                        
                    if action['type'] == 'select' and 'selected_options' in action:
                        for selected in action['selected_options']:
                            matchups_string += attachment['fallback'] + ': ' + selected['text']
                            if score_prediction:
                                if "highest" in attachment['text']:
                                    matchups_string += ', ' + score_prediction['high_score']
                                elif "lowest" in attachment['text']:
                                    matchups_string += ', ' + score_prediction['low_score']
                            if "closest" in attachment['text']:
                                matchups_string += '\n'
                            else:
                                matchups_string += ' | '

            prediction_string += winners_string.rstrip(', ') + '\n' + matchups_string.rstrip('| ')
            message['attachments'].append({ 'text': prediction_string })

        return message

class PredictionCalculations(restful.Resource):
    def post(self):
        if datetime.now() < WEEK_END_TIME:
            return Response()

        year_and_week = LEAGUE_YEAR + '-' + LEAGUE_WEEK
        message = {
            'response_type': 'in_channel',
            'text': 'Prediction calculations for week ' + LEAGUE_WEEK + ' of ' + LEAGUE_YEAR + ':',
            'attachments': []
        }
        results_string = 'Winners: '

        bonus_string = ''
        blowout_matchup, closest_matchup = '', ''
        blowout_winners, closest_winners, highest_winners, lowest_winners = [], [], [], []
        highest_pin_winner, lowest_pin_winner = '', ''
        highest_pin_score, lowest_pin_score = '', ''
        highest_pin_timestamp, lowest_pin_timestamp = '', ''
        highest_timestamp_tiebreaker_used, lowest_timestamp_tiebreaker_used = False, False
        highest_within_one_point, lowest_within_one_point = False, False

        formula_string = 'TOTAL = MATCHUP TOTAL + BLOWOUT BONUS + CLOSEST BONUS + HIGHEST BONUS + LOWEST BONUS\n'
        formula_by_user = {}

        standings_string = 'Draft selection standings for the season so far (with lowest score dropped):\n'

        matchup_result = mongo.db.matchup_results.find_one({ 'year_and_week': year_and_week })

        for winner in matchup_result['winners']:
            results_string += winner + ', '

        results_string = results_string.rstrip(', ') + '\n'

        for prediction in mongo.db.predictions.find({ 'year_and_week': year_and_week }):
            username = prediction['username']
            score_prediction = mongo.db.score_predictions.find_one({ 'username': username, 'year_and_week': year_and_week })
            user_winners = []
            user_formula = {
                'username': username,
                'matchup_total': 0,
                'blowout_bonus': 0,
                'closest_bonus': 0,
                'highest_bonus': 0,
                'lowest_bonus': 0
            }

            for attachment in prediction['message']['attachments']:
                for action in attachment['actions']:
                    if action['type'] == 'button' and action['style'] == 'primary':
                        user_winners.append(action['text'])
                        if action['text'] in matchup_result['winners']:
                            user_formula['matchup_total'] += 1
                    # calculating winners before highest/lowest on purpose, order of original JSON/form matters here
                    if action['type'] == 'select' and 'blowout' in attachment['text']:
                        if not blowout_matchup:
                            for option in action['options']:
                                if matchup_result['blowout'] in option['text']:
                                    blowout_matchup = option['text']
                        if 'selected_options' in action:
                            for selected in action['selected_options']:
                                if matchup_result['blowout'] in selected['text'] and matchup_result['highest'] in user_winners and username not in blowout_winners:
                                    blowout_winners.append(username)
                                    user_formula['blowout_bonus'] += 1
                    if action['type'] == 'select' and 'closest' in attachment['text']:
                        if not closest_matchup:
                            for option in action['options']:
                                if matchup_result['closest'] in option['text']:
                                    closest_matchup = option['text']
                        if 'selected_options' in action:
                            for selected in action['selected_options']:
                                if matchup_result['closest'] in selected['text'] and username not in closest_winners:
                                    closest_winners.append(username)
                                    user_formula['closest_bonus'] += 1
                    if action['type'] == 'select' and 'highest' in attachment['text'] and 'selected_options' in action:
                        for selected in action['selected_options']:
                            if matchup_result['highest'] in selected['text'] and username not in highest_winners:
                                highest_winners.append(username)
                                user_formula['highest_bonus'] += 1
                                if score_prediction:
                                    if not highest_pin_winner:
                                        highest_pin_winner = username
                                        highest_pin_score = score_prediction['high_score']
                                        highest_pin_timestamp = prediction['message']['ts']
                                    else:
                                        current_distance_to_pin = abs(round(Decimal(highest_pin_score), 1) - round(Decimal(matchup_result['high_score']), 1))
                                        contender_distance_to_pin = abs(round(Decimal(score_prediction['high_score']), 1) - round(Decimal(matchup_result['high_score']), 1))
                                        if current_distance_to_pin > contender_distance_to_pin:
                                            highest_pin_winner = username
                                            highest_pin_score = score_prediction['high_score']
                                            highest_pin_timestamp = prediction['message']['ts']
                                        elif current_distance_to_pin == contender_distance_to_pin:
                                            highest_timestamp_tiebreaker_used = True
                                            # tie goes to earliest prediction, Slack uses float timestamps to guarantee ordering
                                            current_timestamp = float(highest_pin_timestamp)
                                            contender_timestamp = float(prediction['message']['ts'])
                                            if current_timestamp > contender_timestamp:
                                                highest_pin_winner = username
                                                highest_pin_score = score_prediction['high_score']
                                                highest_pin_timestamp = prediction['message']['ts']
                                    current_distance_to_pin = abs(round(Decimal(highest_pin_score), 1) - round(Decimal(matchup_result['high_score']), 1))
                                    if current_distance_to_pin <= 1:
                                        highest_within_one_point = True
                                    
                    if action['type'] == 'select' and 'lowest' in attachment['text'] and 'selected_options' in action:
                        for selected in action['selected_options']:
                            if matchup_result['lowest'] in selected['text'] and username not in lowest_winners:
                                lowest_winners.append(username)
                                user_formula['lowest_bonus'] += 1
                                if score_prediction:
                                    if not lowest_pin_winner:
                                        lowest_pin_winner = username
                                        lowest_pin_score = score_prediction['low_score']
                                        lowest_pin_timestamp = prediction['message']['ts']
                                    else:
                                        current_distance_to_pin = abs(round(Decimal(lowest_pin_score), 1) - round(Decimal(matchup_result['low_score']), 1))
                                        contender_distance_to_pin = abs(round(Decimal(score_prediction['low_score']), 1) - round(Decimal(matchup_result['low_score']), 1))
                                        if current_distance_to_pin > contender_distance_to_pin:
                                            lowest_pin_winner = username
                                            lowest_pin_score = score_prediction['low_score']
                                            lowest_pin_timestamp = prediction['message']['ts']
                                        elif current_distance_to_pin == contender_distance_to_pin:
                                            lowest_timestamp_tiebreaker_used = True
                                            # tie goes to earliest prediction, Slack uses float timestamps to guarantee ordering
                                            current_timestamp = float(lowest_pin_timestamp)
                                            contender_timestamp = float(prediction['message']['ts'])
                                            if current_timestamp > contender_timestamp:
                                                lowest_pin_winner = username
                                                lowest_pin_score = score_prediction['low_score']
                                                lowest_pin_timestamp = prediction['message']['ts']
                                    current_distance_to_pin = abs(round(Decimal(lowest_pin_score), 1) - round(Decimal(matchup_result['low_score']), 1))
                                    if current_distance_to_pin <= 1:
                                        lowest_within_one_point = True
            # after processing all this user's selections
            formula_by_user[username] = user_formula

        results_string += 'Blowout: ' + blowout_matchup + ' | Closest: ' + closest_matchup + '\n'
        results_string += 'Highest: ' + matchup_result['highest'] + ', ' + matchup_result['high_score'] + ' | '
        results_string += 'Lowest: ' + matchup_result['lowest'] + ', ' + matchup_result['low_score']
        message['attachments'].append({ 'text': results_string })

        if not blowout_winners:
            bonus_string += 'No one'
        else:
            bonus_string += ', '.join(blowout_winners[:-2] + [' and '.join(blowout_winners[-2:])])
        bonus_string += ' got a point for guessing the biggest blowout.\n'
        if not closest_winners:
            bonus_string += 'No one'
        else:
            bonus_string += ', '.join(closest_winners[:-2] + [' and '.join(closest_winners[-2:])])
        bonus_string += ' got a point for guessing the matchup with the closest margin of victory.\n'
        if not highest_winners:
            bonus_string += 'No one'
        else:
            bonus_string += ', '.join(highest_winners[:-2] + [' and '.join(highest_winners[-2:])])
        bonus_string += ' got a point for guessing the highest scorer'
        if highest_pin_winner:
            formula_by_user[highest_pin_winner]['highest_bonus'] += 1
            bonus_string += ', with ' + highest_pin_winner + ' getting an extra point for guessing the closest score'
        if highest_timestamp_tiebreaker_used:
            bonus_string += ' (earliest prediction tiebreaker was used)'
        if highest_within_one_point:
            formula_by_user[highest_pin_winner]['highest_bonus'] += 1
            bonus_string += '. ' + highest_pin_winner + ' got a third point for guessing the score within a point, after rounding'
        bonus_string += '.\n'
        if not lowest_winners:
            bonus_string += 'No one'
        else:
            bonus_string += ', '.join(lowest_winners[:-2] + [' and '.join(lowest_winners[-2:])])
        bonus_string += ' got a point for guessing the lowest scorer'
        if lowest_pin_winner:
            formula_by_user[lowest_pin_winner]['lowest_bonus'] += 1
            bonus_string += ', with ' + lowest_pin_winner + ' getting an extra point for guessing the closest score'
        if lowest_timestamp_tiebreaker_used:
            bonus_string += ' (earliest prediction tiebreaker was used)'
        if lowest_within_one_point:
            formula_by_user[lowest_pin_winner]['lowest_bonus'] += 1
            bonus_string += '. ' + lowest_pin_winner + ' got a third point for guessing the score within a point, after rounding'
        bonus_string += '.\n'
        message['attachments'].append({ 'text': bonus_string })

        prediction_formula = lambda x: x['matchup_total'] + x['blowout_bonus'] + x['closest_bonus'] + x['highest_bonus'] + x['lowest_bonus']
        user_formulas = sorted(formula_by_user.values(), key=prediction_formula, reverse=True)
        if int(LEAGUE_WEEK) == 1:
            users_without_predictions = list(set(LEAGUE_USERNAMES) - set(formula_by_user.keys()))
            for username in users_without_predictions:
                database_key = { 'username': username, 'year_and_week': year_and_week }
                mongo.db.prediction_standings.update(database_key, {
                    '$set': {
                        'total': 0,
                        'low': 0
                    },
                }, upsert=True, multi=False)
        for user_formula in user_formulas:
            formula_total = prediction_formula(user_formula)
            database_key = { 'username': user_formula['username'], 'year_and_week': year_and_week }
            if int(LEAGUE_WEEK) == 1:
                mongo.db.prediction_standings.update(database_key, {
                    '$set': {
                        'total': 0,
                        'low': formula_total
                    },
                }, upsert=True, multi=False)
            user_formula_string = user_formula['username'] + ': ' + str(formula_total) + ' = ' + str(user_formula['matchup_total']) + ' + ' + str(user_formula['blowout_bonus']) + ' + ' + str(user_formula['closest_bonus']) + ' + ' + str(user_formula['highest_bonus']) + ' + ' + str(user_formula['lowest_bonus'])
            formula_string += user_formula_string + '\n'
        message['attachments'].append({ 'text': formula_string })

        if int(LEAGUE_WEEK) > 1:
            last_week = int(LEAGUE_WEEK) - 1
            year_and_last_week = LEAGUE_YEAR + '-' + str(last_week)
            for prediction_record in mongo.db.prediction_standings.find({ 'year_and_week': year_and_last_week }):
                username = prediction_record['username']
                database_key = { 'username': username, 'year_and_week': year_and_week }
                formula_total = prediction_formula(formula_by_user[username])
                if formula_total < prediction_record['low']:
                    mongo.db.prediction_standings.update(database_key, {
                        '$set': {
                            'total': prediction_record['total'] + prediction_record['low'],
                            'low': formula_total
                        },
                    }, upsert=True, multi=False)
                else:
                    mongo.db.prediction_standings.update(database_key, {
                        '$set': {
                            'total': prediction_record['total'] + formula_total,
                        },
                    }, upsert=True, multi=False)

        for prediction_record in mongo.db.prediction_standings.find({ 'year_and_week': year_and_week }).sort([('total', -1), ('low', -1)]):
            standings_string += prediction_record['username'] + ' - ' + str(prediction_record['total']) + '; LOW: ' + str(prediction_record['low']) + '\n'
        message['attachments'].append({ 'text': standings_string })

        return message

api.add_resource(Root, '/')
api.add_resource(Scoreboard, '/scoreboard/')
api.add_resource(Prediction, '/prediction/')
api.add_resource(ScorePrediction, '/prediction/score/')
api.add_resource(SendPredictionForm, '/prediction/form/')
api.add_resource(PredictionSubmissions, '/prediction/submissions/')
api.add_resource(PredictionCalculations, '/prediction/calculations/')
