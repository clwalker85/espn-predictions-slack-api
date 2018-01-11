import os
import json
import pprint
import requests
import traceback
from decimal import Decimal
from datetime import datetime
from espnff import League
from flask import request, abort, Response
from flask.ext import restful
from flask_rest_service import app, api, mongo, post_to_slack, LEAGUE_ID, LEAGUE_MEMBERS, LEAGUE_USERNAMES, LEAGUE_YEAR, LEAGUE_WEEK, DEADLINE_STRING, DEADLINE_TIME, WEEK_END_TIME, MATCHUPS

# simple proof of concept that I could get Mongo working in Heroku
@app.route('/', methods=['GET', 'POST'])
def root(self):
    return {
        'status': 'OK',
        'mongo': str(mongo.db),
    }

# TODO - Add a scoreboard command when the ESPN API can be used with our league
# https://github.com/rbarton65/espnff/pull/41
@app.route('/scoreboard/', methods=['POST'])
def scoreboard(self):
    #league = League(LEAGUE_ID, LEAGUE_YEAR)
    #pprint.pformat(league)
    #pprint.pformat(league.scoreboard())
    return Response()

# FIRST TIME LOOKING AT THIS CODE??? Good. Start looking here.
# Understanding the JSON structure sent back and forth to Slack is key to understanding this code.

# First, we send an "interactive message" to slack, which ends up looking like the prediction form:
# - https://api.slack.com/interactive-messages
# - See the send_prediction_form function for more details on how this JSON structure is built.
# - See the post_to_slack function in __init__.py for details on how this is sent to people in Slack.

# Second, when someone clicks on a button in this prediction form, the response is sent to this
# function. This code is a guide to finding the important info in the JSON, particularly how to
# determine if a button or dropdown was chosen. We also add some styling to the button or make
# the dropdown show the selection.

# Finally, the JSON we just changed in little ways is sent back to Slack, where it replaces the
# previous prediction form. This is crucial because:
# - the form appears to change in place
# - we literally save exactly what the user sees, so problems are immediately obvious
# - if the POST errors, the form isn't replaced, and the user sees their selection wasn't made
@app.route('/prediction/', methods=['POST'])
def save_prediction_from_slack(self):
    # block the prediction submission if it's after the deadline
    # an empty response to an interactive message action will make sure
    # the original message is unchanged, so it'll appear the form is unchanged and unresponsive
    if datetime.now() > DEADLINE_TIME:
        return Response()

    payload = json.loads(request.form.get('payload', None))

    username = payload['user']['name']
    year_and_week = payload['callback_id']
    # TODO - I don't know why I combined year and week to make a unique key, split them up
    database_key = { 'username': username, 'year_and_week': year_and_week }
    message = payload['original_message']
    actions = payload['actions']

    for attachment in message['attachments']:
        # loop through each interactive message action, basically what changed
        for action in actions:
            # loop through each part of the prediction form
            for element in attachment['actions']:
                if element['type'] == 'button' and action['name'] == element['name'] and action['value'] == element['value']:
                    # color the button green to show it's selected
                    attachment['color'] = 'good'
                    element['style'] = 'primary'

                if element['type'] == 'button' and action['name'] == element['name'] and action['value'] != element['value']:
                    # remove any coloring if it's not selected
                    element['style'] = None

                if element['type'] == 'select' and action['name'] == element['name']:
                    # color the dropdown green to show it was changed
                    attachment['color'] = 'good'
                    element['selected_options'] = []
                    # only one option should be selected, but Slack supports multiple
                    for selected in action['selected_options']:
                        # loop through this dropdown's available options
                        for option in element['options']:
                            if option['value'] == selected['value']:
                                # this is how you pre-select an option in a dropdown
                                element['selected_options'].append(option)

    # save that shit every time, and mark the last time they saved
    mongo.db.predictions.update(database_key, {
        '$set': {
            'message': message,
            'last_modified': datetime.now()
        },
    # insert if you need to, and make sure to guarantee one record per user and year/week
    }, upsert=True, multi=False)


    # Slack replaces old prediction form with any immediate response,
    # so return the form again with any selected buttons styled
    return message

# TODO - I don't know why I have a separate table for scores, combine this with prediction form JSON
@app.route('/prediction/score/', methods=['POST'])
def save_score_prediction(self):
    # block the score submission if it's after the deadline
    # since it's a direct Slack command, you'll need to respond with an error message
    if datetime.now() > DEADLINE_TIME:
        return 'Prediction not saved for week ' + LEAGUE_WEEK + '. Deadline of ' + DEADLINE_STRING + ' has passed.'

    # for direct Slack commands, you don't get a payload like an interactive message action,
    # you have to parse the text of the parameters
    text = request.form.get('text', None)
    username = request.form.get('user_name', None)
    # TODO - I don't know why I combined year and week to make a unique key, split them up
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

        # we don't care about the order of these params
        if first_score < second_score:
            high_score = param[1]
            low_score = param[0]

        mongo.db.score_predictions.update(database_key, {
            '$set': {
                'high_score': high_score,
                'low_score': low_score,
                'last_modified': datetime.now()
            },
        }, upsert=True, multi=False)

        return 'Prediction successfully saved for week ' + LEAGUE_WEEK + '! High score: ' + high_score + ', low score: ' + low_score
    except:
        return 'Prediction not saved for week ' + LEAGUE_WEEK + '. Type in valid decimal numbers next time.'

    return 'Prediction not saved for week ' + LEAGUE_WEEK + '.'

# This method loops through any saved predictions for the current week and posts them
# in response to whoever ran the command in Slack. It's also a good way to understand the
# JSON object that's passed back and forth (and saved) for predictions.
@app.route('/prediction/submissions/', methods=['GET', 'POST'])
def get_submitted_predictions(self):
    # block the ability to see everyone's predictions unless the submission deadline has passed
    # TODO - I could respond to a direct Slack command with an error message here
    if datetime.now() < DEADLINE_TIME:
        return Response()

    # TODO - I don't know why I combined year and week to make a unique key, split them up
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

        # TODO - I don't know why I have a separate table for scores, combine this with prediction form JSON
        score_prediction = mongo.db.score_predictions.find_one({ 'username': username, 'year_and_week': year_and_week })

        for attachment in prediction['message']['attachments']:
            for action in attachment['actions']:
                # if a button is marked as 'primary', it's selected, so put it with the winners
                if action['type'] == 'button' and action['style'] == 'primary':
                    winners_string += action['text'] + ', '
                    
                # if a dropdown has a selection
                if action['type'] == 'select' and 'selected_options' in action:
                    # I guess a dropdown can have multiple selections
                    # but this looks better than picking the first one
                    # TODO - maybe there's a cleaner/more-Python way to pick the first one
                    for selected in action['selected_options']:
                        # I'm counting on the fallback key holding the name of the dropdown,
                        # so prepend the selection with this name
                        matchups_string += attachment['fallback'] + ': ' + selected['text']
                        # if there's a score prediction, add that too
                        if score_prediction:
                            if "highest" in attachment['text']:
                                matchups_string += ', ' + score_prediction['high_score']
                            elif "lowest" in attachment['text']:
                                matchups_string += ', ' + score_prediction['low_score']
                        # just an attempt to fit more information on one line
                        # this assumes that the prediction form I'm looping over
                        # has an order of blowout/closest/highest/lowest
                        if "closest" in attachment['text']:
                            matchups_string += '\n'
                        else:
                            matchups_string += ' | '

        # strip the last comma or pipe delimiter
        prediction_string += winners_string.rstrip(', ') + '\n' + matchups_string.rstrip('| ')
        # one message attachment per user
        message['attachments'].append({ 'text': prediction_string })

    return message

# This is how the sausage is made. This code is pretty boring, but it lays out pretty explicitly
# the JSON that makes up the prediction form. See the "interactive message" docs for more details:
# https://api.slack.com/interactive-messages
@app.route('/prediction/form/', methods=['GET', 'POST'])
def send_prediction_form(self):
    message = {
        'text': 'Make your predictions for week ' + LEAGUE_WEEK + ' matchups below by ' + DEADLINE_STRING + ':',
        'attachments': []
    }
    for index, matchup in enumerate(MATCHUPS):
        message['attachments'].append({
            'text': matchup[0],
            'attachment_type': 'default',
            # TODO - I don't know why I combined year and week to make a unique key, split them up
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
        # the intent of 'fallback' seems to be to provide some screenreader/accesibility support,
        # but it also works to support what we display when we report everyone's predictions
        # for the week, so this is coupled to the functionality in get_submitted_predictions
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

    # defined in __init__.py, this file should only be for defining Slack plugin endpoints
    post_to_slack(message)

    return Response()

# WARNING - I saved the most complicated code for the end. If you skipped the stuff above,
# fucking stop and go reread that shit.
@app.route('/prediction/calculations/', methods=['GET', 'POST'])
def calculate_predictions(self):
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

    # TODO - I have to enter matchup results by hand each week when scoring is final on Tuesday
    # maybe we can make the scoreboard command load this table
    matchup_result = mongo.db.matchup_results.find_one({ 'year_and_week': year_and_week })

    for winner in matchup_result['winners']:
        results_string += winner + ', '

    results_string = results_string.rstrip(', ') + '\n'

    # loop through each prediction for this week
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

        # loop through each group of buttons or dropdowns
        for attachment in prediction['message']['attachments']:
            # loop through each button/dropdown in each group
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
                            # can't win the blowout bonus if you don't predict the right winner
                            if matchup_result['blowout'] in selected['text'] and matchup_result['blowout'] in user_winners and username not in blowout_winners:
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
                                # no highest recorded so far? you're the winner by default
                                if not highest_pin_winner:
                                    highest_pin_winner = username
                                    highest_pin_score = score_prediction['high_score']
                                    highest_pin_timestamp = prediction['last_modified']
                                # already have a highest? there can only be one!
                                else:
                                    # round score predictions and actual recorded scores, then compare
                                    current_distance_to_pin = abs(round(Decimal(highest_pin_score), 1) - round(Decimal(matchup_result['high_score']), 1))
                                    contender_distance_to_pin = abs(round(Decimal(score_prediction['high_score']), 1) - round(Decimal(matchup_result['high_score']), 1))
                                    if current_distance_to_pin > contender_distance_to_pin:
                                        highest_pin_winner = username
                                        highest_pin_score = score_prediction['high_score']
                                        highest_pin_timestamp = prediction['last_modified']
                                    # in the case of a tie, use the earliest prediction
                                    # TODO - find a more graceful way to prevent ties
                                    elif current_distance_to_pin == contender_distance_to_pin:
                                        highest_timestamp_tiebreaker_used = True
                                        current_timestamp = float(highest_pin_timestamp)
                                        contender_timestamp = float(prediction['last_modified'])
                                        if current_timestamp and current_timestamp > contender_timestamp:
                                            highest_pin_winner = username
                                            highest_pin_score = score_prediction['high_score']
                                            highest_pin_timestamp = prediction['last_modified']
                                current_distance_to_pin = abs(round(Decimal(highest_pin_score), 1) - round(Decimal(matchup_result['high_score']), 1))
                                # we round because the exact match rule we're resolving below
                                # predates the time we changed to decimal scoring
                                if current_distance_to_pin <= 1:
                                    highest_within_one_point = True
                                
                # see comments on highest methodology above
                # TODO - Is there a way to get rid of this mostly copied code?
                if action['type'] == 'select' and 'lowest' in attachment['text'] and 'selected_options' in action:
                    for selected in action['selected_options']:
                        if matchup_result['lowest'] in selected['text'] and username not in lowest_winners:
                            lowest_winners.append(username)
                            user_formula['lowest_bonus'] += 1
                            if score_prediction:
                                if not lowest_pin_winner:
                                    lowest_pin_winner = username
                                    lowest_pin_score = score_prediction['low_score']
                                    lowest_pin_timestamp = prediction['last_modified']
                                else:
                                    current_distance_to_pin = abs(round(Decimal(lowest_pin_score), 1) - round(Decimal(matchup_result['low_score']), 1))
                                    contender_distance_to_pin = abs(round(Decimal(score_prediction['low_score']), 1) - round(Decimal(matchup_result['low_score']), 1))
                                    if current_distance_to_pin > contender_distance_to_pin:
                                        lowest_pin_winner = username
                                        lowest_pin_score = score_prediction['low_score']
                                        lowest_pin_timestamp = prediction['last_modified']
                                    elif current_distance_to_pin == contender_distance_to_pin:
                                        lowest_timestamp_tiebreaker_used = True
                                        current_timestamp = float(lowest_pin_timestamp)
                                        contender_timestamp = float(prediction['last_modified'])
                                        if current_timestamp and current_timestamp > contender_timestamp:
                                            lowest_pin_winner = username
                                            lowest_pin_score = score_prediction['low_score']
                                            lowest_pin_timestamp = prediction['last_modified']
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
        bonus_string += ', with ' + highest_pin_winner + ' getting an extra point for guessing the highest score'
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
        bonus_string += ', with ' + lowest_pin_winner + ' getting an extra point for guessing the lowest score'
    if lowest_timestamp_tiebreaker_used:
        bonus_string += ' (earliest prediction tiebreaker was used)'
    if lowest_within_one_point:
        formula_by_user[lowest_pin_winner]['lowest_bonus'] += 1
        bonus_string += '. ' + lowest_pin_winner + ' got a third point for guessing the score within a point, after rounding'
    bonus_string += '.\n'
    message['attachments'].append({ 'text': bonus_string })

    # we gotta reuse this formula in several spots, so defining it here
    prediction_formula = lambda x: x['matchup_total'] + x['blowout_bonus'] + x['closest_bonus'] + x['highest_bonus'] + x['lowest_bonus']
    user_formulas = sorted(formula_by_user.values(), key=prediction_formula, reverse=True)
    if int(LEAGUE_WEEK) == 1:
        # put zeroes there for anyone who missed the first prediction
        # VERY IMPORTANT, cause we assume every league member has a row in this table
        users_without_predictions = list(set(LEAGUE_USERNAMES) - set(formula_by_user.keys()))
        for username in users_without_predictions:
            database_key = { 'username': username, 'year_and_week': year_and_week }
            mongo.db.prediction_standings.update(database_key, {
                '$set': {
                    'total': 0,
                    'low': 0
                },
            }, upsert=True, multi=False)
    # loop through everyone who submitted a prediction this week
    for user_formula in user_formulas:
        formula_total = prediction_formula(user_formula)
        database_key = { 'username': user_formula['username'], 'year_and_week': year_and_week }
        # standings on the first week is trivial and exactly the same as waiver order standings
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
        # go find the standings from last week
        last_week = int(LEAGUE_WEEK) - 1
        year_and_last_week = LEAGUE_YEAR + '-' + str(last_week)
        for prediction_record in mongo.db.prediction_standings.find({ 'year_and_week': year_and_last_week }):
            username = prediction_record['username']
            database_key = { 'username': username, 'year_and_week': year_and_week }

            if username in formula_by_user:
                formula_total = prediction_formula(formula_by_user[username])
            else:
                formula_total = 0

            # current rules say drop the lowest prediction score, so
            # if the current prediction is lower, add the previous low instead
            # and make the current prediction the current low
            if formula_total < prediction_record['low']:
                mongo.db.prediction_standings.update(database_key, {
                    '$set': {
                        'total': prediction_record['total'] + prediction_record['low'],
                        'low': formula_total
                    },
                }, upsert=True, multi=False)
            # otherwise, add the current prediction total as normal
            # and keep the existing low score
            else:
                mongo.db.prediction_standings.update(database_key, {
                    '$set': {
                        'total': prediction_record['total'] + formula_total,
                        'low': prediction_record['low']
                    },
                }, upsert=True, multi=False)

    # sort this shit for ease of calculating waiver order standings
    # TODO - factor in tiebreakers from ESPN standings data
    for prediction_record in mongo.db.prediction_standings.find({ 'year_and_week': year_and_week }).sort([('total', -1), ('low', -1)]):
        standings_string += prediction_record['username'] + ' - ' + str(prediction_record['total']) + '; LOW: ' + str(prediction_record['low']) + '\n'
    message['attachments'].append({ 'text': standings_string })

    return message
