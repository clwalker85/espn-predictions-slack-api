import os
import json
import pprint
import requests
import traceback
import copy
from decimal import Decimal
from datetime import datetime
from espnff import League
from flask import request, abort, Response
from flask.ext import restful
# see __init__.py for these definitions
from flask_rest_service import app, api, mongo, post_to_slack, LEAGUE_ID, LEAGUE_MEMBERS, LEAGUE_USERNAMES, LEAGUE_YEAR, LEAGUE_WEEK, DEADLINE_STRING, DEADLINE_TIME, WEEK_END_TIME, MATCHUPS

# we gotta reuse this formula in several spots, so defining it here
PREDICTION_FORMULA = lambda x: x['matchup_total'] + x['blowout_bonus'] + x['closest_bonus'] + x['highest_bonus'] + x['lowest_bonus']

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
@api.route('/prediction/')
class SavePredictionFromSlack(restful.Resource):
    def post(self):
        payload = json.loads(request.form.get('payload', None))
        # seemed like the best way to store the year and week inside the prediction form
        year, week = payload['callback_id'].split("-")

        # block the prediction submission if it's after the deadline
        # an empty response to an interactive message action will make sure
        # the original message is unchanged, so it'll appear the form is unchanged and unresponsive
        if year != LEAGUE_YEAR or week != LEAGUE_WEEK or datetime.now() > DEADLINE_TIME:
            return Response()

        username = payload['user']['name']
        database_key = { 'username': username, 'year': year, 'week': week }
        message = payload['original_message']
        actions = payload['actions']

        # loop through each interactive message action, basically what changed
        for action in actions:
            # find the prediction form element that matches the action name and style that bitch
            for a in message['attachments']:
                for element in a['actions']:
                    if action['name'] == element['name']:
                        style_form_with_action(element, action, a)

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

def style_form_with_action(element, action, form_group):
    # color that portion of the form to show it was changed
    form_group['color'] = 'good'

    if element['type'] == 'button':
        if action['value'] == element['value']:
            # color the button green to show it's selected
            element['style'] = 'primary'
        else:
            # remove coloring on the button if it's not selected
            element['style'] = None
    elif element['type'] == 'select' and action['selected_options']:
        # I guess Slack supports multiple dropdown selections, but just get the "first" selection
        selected = action['selected_options'][0]
        # for a dropdown element, this is how you mark something as selected
        element['selected_options'] = [option
            for option in element['options'] if option['value'] == selected['value']]

@api.route('/prediction/score/')
class SaveScorePrediction(restful.Resource):
    def post(self):
        # since it's a direct Slack command, you'll need to respond with an error message
        if datetime.now() > DEADLINE_TIME:
            return Response('Prediction not saved for week ' + LEAGUE_WEEK + '. Deadline of ' + DEADLINE_STRING + ' has passed.')

        # for direct Slack commands, you don't get a payload like an interactive message action,
        # you have to parse the text of the parameters
        text = request.form.get('text', None)
        username = request.form.get('user_name', None)
        database_key = { 'username': username, 'year': LEAGUE_YEAR, 'week': LEAGUE_WEEK }
        param = text.split()

        if len(param) < 2:
            return Response('Prediction not saved for week ' + LEAGUE_WEEK + '. Type in two numbers to the score-prediction command for highest and lowest score next time.')

        try:
            first_score = Decimal(param[0])
            second_score = Decimal(param[1])
            high_score = param[0]
            low_score = param[1]

            # we don't care about the order of these params
            if first_score < second_score:
                high_score = param[1]
                low_score = param[0]

            mongo.db.predictions.update(database_key, {
                '$set': {
                    'high_score': high_score,
                    'low_score': low_score,
                    'last_modified': datetime.now()
                },
            }, upsert=True, multi=False)

            return Response('Prediction successfully saved for week ' + LEAGUE_WEEK + '! High score: ' + high_score + ', low score: ' + low_score)
        except:
            return Response('Prediction not saved for week ' + LEAGUE_WEEK + '. Type in valid decimal numbers next time.')

        return Response('Prediction not saved for week ' + LEAGUE_WEEK + '.')

# This method loops through any saved predictions for the current week and posts them
# in response to whoever ran the command in Slack. It's also a good way to understand the
# JSON object that's passed back and forth (and saved) for predictions.
@api.route('/prediction/submissions/')
class GetSubmittedPredictions(restful.Resource):
    def post(self):
        # since it's a direct Slack command, you'll need to respond with an error message
        if datetime.now() < DEADLINE_TIME:
            return Response('Submitted predictions are not visible until the submission deadline has passed.')

        message = {
            'response_type': 'in_channel',
            'text': 'Predictions submitted for week ' + LEAGUE_WEEK + ' of ' + LEAGUE_YEAR + ':',
            'attachments': []
        }

        # for each submitted prediction that week
        for prediction in mongo.db.predictions.find({ 'year': LEAGUE_YEAR, 'week': LEAGUE_WEEK }):
            username = prediction['username']
            form_groups = prediction['message']['attachments']
            prediction_string = username + ' picks: '

            predicted_winners = [element['text']
                for g in form_groups for element in g['actions'] if is_button_selected(element)]
            prediction_string += ', '.join(predicted_winners) + '\n'

            dropdown_selections = [format_dropdown_selection(element, g, prediction)
                for g in form_groups for element in g['actions'] if is_dropdown_selected(element)]
            prediction_string += ' | '.join(dropdown_selections)

            # one message attachment per user
            message['attachments'].append({ 'text': prediction_string })

        return message

def is_button_selected(element):
    return element['type'] == 'button' and element['style'] == 'primary'

def is_dropdown_selected(element):
    return element['type'] == 'select' and element['selected_options']

def format_dropdown_selection(element, form_group, prediction):
    selected = element['selected_options'][0]
    # I'm counting on the fallback key holding the name of the dropdown,
    # so prepend the selection with this name
    selected_string = form_group['fallback'] + ': ' + selected['text']

    # if there's a score prediction, add that too
    if 'high_score' in prediction and 'low_score' in prediction:
        if "highest" in form_group['text']:
            selected_string += ', ' + prediction['high_score']
        elif "lowest" in form_group['text']:
            selected_string += ', ' + prediction['low_score']

    return selected_string

# This is how the sausage is made. This code is pretty boring, but it lays out pretty explicitly
# the JSON that makes up the prediction form. See the "interactive message" docs for more details:
# https://api.slack.com/interactive-messages
@api.route('/prediction/form/')
class SendPredictionForm(restful.Resource):
    def get(self):
        message = {
            'text': 'Make your predictions for week ' + LEAGUE_WEEK + ' matchups below by ' + DEADLINE_STRING + ':',
            'attachments': []
        }
        # seemed like the best way to store the year and week inside the prediction form
        callback_id = LEAGUE_YEAR + '-' + LEAGUE_WEEK

        for index, matchup in enumerate(MATCHUPS):
            message['attachments'].append({
                'text': matchup['team_one'] + ' versus ' + matchup['team_two'],
                'attachment_type': 'default',
                'callback_id': callback_id,
                'actions': [
                    {
                        # buttons in the same form group need to match on name to be styled properly
                        'name': 'winner' + str(index),
                        'text': matchup['team_one'],
                        'type': 'button',
                        'value': matchup['team_one']
                    },
                    {
                        'name': 'winner' + str(index),
                        'text': matchup['team_two'],
                        'type': 'button',
                        'value': matchup['team_two']
                    }
                ]
            })

        dropdown_template = {
            'text': 'Which matchup will have the biggest blowout?',
            # the intent of 'fallback' seems to be to provide some screenreader/accesibility support,
            # but it also works to support what we display when we report everyone's predictions
            # for the week, so this is coupled to the functionality in GetSubmittedPredictions
            'fallback': 'Blowout',
            'attachment_type': 'default',
            'callback_id': callback_id,
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
            dropdown_template['actions'][0]['options'].append({
                'text': matchup['team_one'] + ' versus ' + matchup['team_two'],
                'value': matchup['team_one'] + ' versus ' + matchup['team_two']
            })
        message['attachments'].append(dropdown_template)

        # reuse our existing dropdown object for the rest
        dropdown = copy.deepcopy(dropdown_template)
        dropdown['text'] = 'Which matchup will have the closest score?'
        dropdown['fallback'] = 'Closest'
        dropdown['actions'][0]['name'] = 'closest'
        message['attachments'].append(dropdown)

        # highest/lowest dropdowns should list teams, not matchups
        dropdown_template['actions'][0]['text'] = 'Pick a team...'
        dropdown_template['actions'][0]['options'] = [ { 'text': name, 'value': name } for name in LEAGUE_MEMBERS ]

        dropdown = copy.deepcopy(dropdown_template)
        dropdown['text'] = 'Who will be the highest scorer?'
        dropdown['fallback'] = 'Highest'
        dropdown['actions'][0]['name'] = 'highest'
        message['attachments'].append(dropdown)

        dropdown = copy.deepcopy(dropdown_template)
        dropdown['text'] = 'Who will be the lowest scorer?'
        dropdown['fallback'] = 'Lowest'
        dropdown['actions'][0]['name'] = 'lowest'
        message['attachments'].append(dropdown)

        # defined in __init__.py
        post_to_slack(message)

        return Response()

# WARNING - I saved the most complicated code for the end. If you skipped the stuff above,
# fucking stop and go reread that shit.
@api.route('/prediction/calculations/')
class CalculatePredictions(restful.Resource):
    def post(self):
        # since it's a direct Slack command, you'll need to respond with an error message
        if datetime.now() < WEEK_END_TIME:
            return Response('Prediction calculations are not available until the morning (8am) after Monday Night Football.')

        message = {
            'response_type': 'in_channel',
            'text': 'Prediction calculations for week ' + LEAGUE_WEEK + ' of ' + LEAGUE_YEAR + ':',
            'attachments': []
        }
        # TODO - I have to enter matchup results by hand each week when scoring is final on Tuesday;
        # maybe we can make the scoreboard command load this table
        matchup_result = mongo.db.matchup_results.find_one({ 'year': LEAGUE_YEAR, 'week': LEAGUE_WEEK })
        formula_by_user, prediction_winners, closest_to_pin_stats = build_prediction_stats(matchup_result)

        message['attachments'].append({ 'text': build_results_string(matchup_result, closest_to_pin_stats) })
        message['attachments'].append({ 'text': build_bonus_string(prediction_winners, closest_to_pin_stats) })
        message['attachments'].append({ 'text': build_formula_string(formula_by_user) })

        # first update the standings, then print the results
        update_prediction_standings(formula_by_user)
        message['attachments'].append({ 'text': build_formula_string(formula_by_user) })

        return message

def build_results_string(result, stats):
    results_string = 'Winners: ' + ', '.join(result['winners']) + '\n'
    results_string += 'Blowout: ' + stats['blowout_matchup']
    results_string += ' | Closest: ' + stats['closest_matchup'] + '\n'
    results_string += 'Highest: ' + result['highest'] + ', ' + result['high_score'] + ' | '
    results_string += 'Lowest: ' + result['lowest'] + ', ' + result['low_score']
    return results_string

def build_bonus_string(winners, stats):
    bonus_string = ''

    if not winners['blowout']:
        bonus_string += 'No one'
    else:
        bonus_string += ', '.join(winners['blowout'][:-2] + [' and '.join(winners['blowout'][-2:])])
    bonus_string += ' got a point for guessing the biggest blowout.\n'

    if not winners['closest']:
        bonus_string += 'No one'
    else:
        bonus_string += ', '.join(winners['closest'][:-2] + [' and '.join(winners['closest'][-2:])])
    bonus_string += ' got a point for guessing the matchup with the closest margin of victory.\n'

    if not winners['highest']:
        bonus_string += 'No one'
    else:
        bonus_string += ', '.join(winners['highest'][:-2] + [' and '.join(winners['highest'][-2:])])
    bonus_string += ' got a point for guessing the highest scorer'
    highest_pin_winner = stats['highest_pin_winner']
    if highest_pin_winner:
        formula_by_user[highest_pin_winner]['highest_bonus'] += 1
        bonus_string += ', with ' + highest_pin_winner + ' getting an extra point for guessing the highest score'
    if stats['highest_within_one_point']:
        formula_by_user[highest_pin_winner]['highest_bonus'] += 1
        bonus_string += '. ' + highest_pin_winner + ' got a third point for guessing the score within a point, after rounding'
    bonus_string += '.\n'

    if not winners['lowest']:
        bonus_string += 'No one'
    else:
        bonus_string += ', '.join(winners['lowest'][:-2] + [' and '.join(winners['lowest'][-2:])])
    bonus_string += ' got a point for guessing the lowest scorer'
    lowest_pin_winner = stats['lowest_pin_winner']
    if lowest_pin_winner:
        formula_by_user[lowest_pin_winner]['lowest_bonus'] += 1
        bonus_string += ', with ' + lowest_pin_winner + ' getting an extra point for guessing the lowest score'
    if stats['lowest_within_one_point']:
        formula_by_user[lowest_pin_winner]['lowest_bonus'] += 1
        bonus_string += '. ' + lowest_pin_winner + ' got a third point for guessing the score within a point, after rounding'
    bonus_string += '.\n'

    return bonus_string

def build_formula_string(formula_by_user):
    formula_string = 'TOTAL = MATCHUP TOTAL + BLOWOUT BONUS + CLOSEST BONUS + HIGHEST BONUS + LOWEST BONUS\n'
    user_formulas = sorted(formula_by_user.values(), key=PREDICTION_FORMULA, reverse=True)
    for user_formula in user_formulas:
        formula_string += user_formula['username'] + \
            ': ' + str(formula_total) + \
            ' = ' + str(user_formula['matchup_total']) + \
            ' + ' + str(user_formula['blowout_bonus']) + \
            ' + ' + str(user_formula['closest_bonus']) + \
            ' + ' + str(user_formula['highest_bonus']) + \
            ' + ' + str(user_formula['lowest_bonus']) + '\n'
    return formula_string

def build_standings_string():
    standings = mongo.db.prediction_standings.find({ 'year': LEAGUE_YEAR, 'week': LEAGUE_WEEK }).sort(
        # sort this shit for ease of calculating waiver order standings
        # TODO - factor in tiebreakers from ESPN standings data
        [('total', -1), ('low', -1)])
    standings_string = 'Draft selection standings for the season so far (with lowest score dropped):\n'
    for prediction_record in standings:
        standings_string += prediction_record['username'] + \
            ' - ' + str(prediction_record['total']) + \
            '; LOW: ' + str(prediction_record['low']) + '\n'
    return standings_string

def build_prediction_stats(result):
    formula_by_user, winners, stats = {}, {}, {}
    actual_winners = result['winners']
    for prediction in mongo.db.predictions.find({ 'year': LEAGUE_YEAR, 'week': LEAGUE_WEEK }):
        username = prediction['username']
        form_groups = prediction['message']['attachments']
        user_formula = {
            'username': username,
            'matchup_total': 0,
            'blowout_bonus': 0,
            'closest_bonus': 0,
            'highest_bonus': 0,
            'lowest_bonus': 0
        }

        # HACK - Must find matchup string, e.g., "Freddy versus Walker", in the prediction form
        # TODO - Maybe I can store this in matchup_results along with the matchup winner
        if 'blowout_matchup' not in stats or 'closest_matchup' not in stats:
            stats['blowout_matchup'], stats['closest_matchup'] = (
                set_matchup_display_strings(form_groups, result))

        # under this logic, that button text better match what's listed in the matchup_results table
        # TODO - Maybe not store matchup_results using names like "Freddy" or "Walker"
        # TODO - Also note the button's text and value can be different things, could use this
        winners['matchup'] = [element['text']
            for g in form_groups for element in g['actions'] if is_button_selected(element)]
        # find intersection of predicted and actual winners, and add that count to the total
        user_formula['matchup_total'] += len(set(winners['matchup']) & set(actual_winners))

        winners['blowout'] += [username
            for g in form_groups for element in g['actions']
            if is_blowout_winner_predicted(element, g, result, winners['matchup'])]
        if username in winners['blowout']:
            user_formula['blowout_bonus'] += 1

        winners['closest'] += [username
            for g in form_groups for element in g['actions']
            if is_closest_predicted(element, g, result)]
        if username in winners['closest']:
            user_formula['closest_bonus'] += 1

        winners['highest'] += [username
            for g in form_groups for element in g['actions']
            if is_highest_predicted(element, g, result)]
        if username in winners['highest']:
            user_formula['highest_bonus'] += 1
            if 'high_score' in prediction:
                stats['highest_pin_winner'], stats['highest_pin_score'], stats['highest_within_one_point'] = (
                    set_closest_to_pin_variables(username, prediction['high_score'], result['high_score'], stats['highest_pin_winner'], stats['highest_pin_score']))

        winners['lowest'] += [username
            for g in form_groups for element in g['actions']
            if is_lowest_predicted(element, g, result)]
        if username in winners['lowest']:
            user_formula['lowest_bonus'] += 1
            if 'low_score' in prediction:
                stats['lowest_pin_winner'], stats['lowest_pin_score'], stats['lowest_within_one_point'] = (
                    set_closest_to_pin_variables(username, prediction['low_score'], result['low_score'], stats['lowest_pin_winner'], stats['lowest_pin_score']))

        # after processing all this user's selections
        formula_by_user[username] = user_formula
    return (formula_by_user, winners, stats)

def set_matchup_display_strings(form_groups, result):
    blowout_matchup, closest_matchup = '', ''
    for form_group in form_groups:
        # loop through each button/dropdown in each group
        for action in form_group['actions']:
            if is_blowout_selected(element, g):
                for option in action['options']:
                    if result['blowout'] in option['text']:
                        blowout_matchup = option['text']
            if is_closest_selected(element, g):
                for option in action['options']:
                    if result['closest'] in option['text']:
                        closest_matchup = option['text']
    return (blowout_matchup, closest_matchup)

def is_blowout_selected(element, form_group):
    return is_dropdown_selected(element) and 'blowout' in form_group['text']

def is_blowout_winner_predicted(element, form_group, result, winners):
    return is_blowout_selected(element, form_group) and result['blowout'] in element['text'] and result['blowout'] in winners

def is_blowout_selected(element, form_group):
    return is_dropdown_selected(element) and 'closest' in form_group['text']

def is_closest_predicted(element, form_group, result):
    return is_closest_selected(element, form_group) and result['closest'] in element['text']

def is_highest_selected(element, form_group):
    return is_dropdown_selected(element) and 'highest' in form_group['text']

def is_highest_predicted(element, form_group, result):
    selected = element['selected_options'][0]
    return is_highest_selected(element, form_group) and result['highest'] in selected['text']

def is_lowest_selected(element, form_group):
    return is_dropdown_selected(element) and 'lowest' in form_group['text']

def is_lowest_predicted(element, form_group, result):
    selected = element['selected_options'][0]
    return is_lowest_selected(element, form_group) and result['lowest'] in selected['text']

def set_closest_to_pin_variables(candidate_winner, candidate_score, actual_score, current_winner, current_closest_score):
    candidate_score_decimal = round(Decimal(candidate_score), 1)
    actual_score_decimal = round(Decimal(actual_score), 1)
    current_closest_decimal = round(Decimal(current_closest_score), 1)
    candidate_distance_to_pin = abs(candidate_score_decimal - actual_score_decimal)
    current_distance_to_pin = abs(current_closest_decimal - actual_score_decimal)
    # we round above because the exact match rule we're resolving below
    # predates the time we changed to decimal scoring
    closest_within_one_point = candidate_distance_to_pin <= 1

    # no highest/lowest recorded so far? you're the winner by default
    if not current_winner and not current_closest_to_pin:
        return (candidate_winner, candidate_score, closest_within_one_point)
    # already have a highest/lowest? there can only be one!
    elif current_distance_to_pin > candidate_distance_to_pin:
        return (candidate_winner, candidate_score, closest_within_one_point)
    return (current_winner, current_score, current_distance_to_pin <= 1)

def update_prediction_standings(formula_by_user):
    if int(LEAGUE_WEEK) == 1:
        # put zeroes there for anyone who missed the first prediction
        # VERY IMPORTANT, cause we assume every league member has a row in this table
        users_without_predictions = list(set(LEAGUE_USERNAMES) - set(formula_by_user.keys()))
        for username in users_without_predictions:
            database_key = { 'username': username, 'year': LEAGUE_YEAR, 'week': LEAGUE_WEEK }
            mongo.db.prediction_standings.update(database_key, {
                '$set': {
                    'total': 0,
                    'low': 0
                },
            }, upsert=True, multi=False)
    # loop through everyone who submitted a prediction this week
    for user_formula in formula_by_user.values():
        formula_total = PREDICTION_FORMULA(user_formula)
        database_key = { 'username': user_formula['username'], 'year': LEAGUE_YEAR, 'week': LEAGUE_WEEK }
        # standings on the first week is trivial and exactly the same as waiver order standings
        if int(LEAGUE_WEEK) == 1:
            mongo.db.prediction_standings.update(database_key, {
                '$set': {
                    'total': 0,
                    'low': formula_total
                },
            }, upsert=True, multi=False)

    if int(LEAGUE_WEEK) > 1:
        last_week = str(int(LEAGUE_WEEK) - 1)
        last_week_standings = mongo.db.prediction_standings.find({ 'year': LEAGUE_YEAR, 'week': last_week })
        for prediction_record in last_week_standings:
            username = prediction_record['username']
            database_key = { 'username': username, 'year': LEAGUE_YEAR, 'week': LEAGUE_WEEK }

            if username in formula_by_user:
                formula_total = PREDICTION_FORMULA(formula_by_user[username])
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
    return
