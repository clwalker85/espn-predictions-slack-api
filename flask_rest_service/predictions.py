import os
import json
import requests
import traceback
import copy
from decimal import Decimal
from datetime import datetime
from flask import request, abort, Response
import flask_restful as restful
# see __init__.py for these definitions
from flask_rest_service import app, api, mongo, metadata, post_to_slack, open_dialog, update_message

# we gotta reuse this formula in several spots, so defining it here
PREDICTION_FORMULA = lambda x: x['matchup_total'] + x['blowout_bonus'] + x['closest_bonus'] + x['highest_bonus'] + x['lowest_bonus']

# FIRST TIME LOOKING AT THIS CODE??? Good. Start looking here.
# Understanding the JSON structure sent back and forth to Slack is key to understanding this code.

# First, we send an "interactive message" to slack, which ends up looking like the prediction form:
# - https://api.slack.com/interactive-messages
# - See the send_prediction_form function for more details on how this JSON structure is built
# - See the post_to_slack function in __init__.py for details on how this is sent to people in Slack

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
        # the original message is unchanged, so it'll appear the form is unresponsive
        if year != metadata.league_year or week != metadata.league_week or datetime.now() > metadata.deadline_time:
            return Response()

        message_type = payload['type']
        actions = payload['actions'] if 'actions' in payload else []

        # dialog submit is the only reason to not return an immediate response
        # see the return at the bottom of this method for more details
        if message_type == 'dialog_submission':
            handle_dialog_submission(payload)
            return Response()
        # we still want to style and save the form on dialog open
        # HACK - this saves a form with no selections if dialog open is first action
        elif any(a['name'] == 'score_submission' for a in actions):
            handle_dialog_display(payload)

        add_styling_to_prediction_form(payload)

        save_form_to_database(payload)

        # Slack replaces old prediction form with any immediate response,
        # so return the form again with any selected buttons styled
        return payload['original_message']

def handle_dialog_display(payload):
    trigger_id = payload['trigger_id']

    # defined in __init__.py
    open_dialog({
        'trigger_id': trigger_id,
        'dialog': build_dialog(payload)
    })

def add_styling_to_prediction_form(payload):
    actions = payload['actions']
    message = payload['original_message']

    # loop through each interactive message action, basically what changed
    for action in actions:
        # find the prediction form element that matches the action name and style it
        for a in message['attachments']:
            for element in a['actions']:
                if action['name'] == element['name']:
                    style_element_with_action(element, action, a)

def style_element_with_action(element, action, form_group):
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

def handle_dialog_submission(payload):
    user_id = payload['user']['id']
    prediction_cursor = get_form_from_database(payload)
    prediction = next(prediction_cursor)
    message = prediction['message']
    score_button = get_score_button(message)
    high_score = payload['submission']['high_score']
    low_score = payload['submission']['low_score']

    try:
        high_decimal = Decimal(high_score)
        low_decimal = Decimal(low_score)

        score_button['text'] = ':heavy_check_mark: High score: ' + high_score + ', Low score: ' + low_score
        save_scores_to_database(payload, message, high_score, low_score)
    # TODO - Catch explicit exceptions for Decimal parsing
    except:
        score_button['text'] = ':x: Type in valid decimal numbers next time. No score predictions currently saved.'
        save_scores_to_database(payload, message, None, None)

    # defined in __init__.py
    update_message({
        'user_id': user_id,
        # we passed the message_ts when the dialog was built through 'state'
        # see build_dialog for more details
        'message_ts': payload['state'],
        'text': message['text'],
        'attachments': message['attachments']
    })

def get_score_button(message):
    attachments = [a for a in message['attachments']]
    # HACK - this code assumes the scores button is at the bottom of the form
    return attachments[-1] if attachments else ''

def get_form_from_database(payload):
    username = payload['user']['name']
    # seemed like the best way to store the year and week inside the prediction form
    year, week = payload['callback_id'].split("-")
    database_key = { 'username': username, 'year': year, 'week': week }
    return mongo.db.predictions.find(database_key)

def save_form_to_database(payload):
    message = payload['original_message']
    username = payload['user']['name']
    # seemed like the best way to store the year and week inside the prediction form
    year, week = payload['callback_id'].split("-")
    database_key = { 'username': username, 'year': year, 'week': week }

    # guarantee one record per user and year/week
    mongo.db.predictions.update_one(database_key, {
        '$set': {
            'message': message,
            'last_modified': datetime.now()
        },
    }, upsert=True)

def save_scores_to_database(payload, message, high_score, low_score):
    username = payload['user']['name']
    # seemed like the best way to store the year and week inside the prediction form
    year, week = payload['callback_id'].split("-")
    database_key = { 'username': username, 'year': year, 'week': week }

    # guarantee one record per user and year/week
    mongo.db.predictions.update_one(database_key, {
        '$set': {
            'message': message,
            'high_score': high_score,
            'low_score': low_score,
            'last_modified': datetime.now()
        },
    }, upsert=True)

# This endpoint loops through any saved predictions for the current week and posts them
# in response to whoever ran the command in Slack. It's also a good way to understand the
# JSON object that's passed back and forth (and saved) for predictions.
@api.route('/prediction/submissions/')
class GetSubmittedPredictions(restful.Resource):
    def post(self):
        metadata.invalidate_cached_week()

        # since it's a direct Slack command, you'll need to respond with an error message
        if datetime.now() < metadata.deadline_time:
            return Response('Submitted predictions are not visible until the submission deadline has passed.')

        message = {
            'response_type': 'in_channel',
            'text': 'Predictions submitted for week ' + metadata.league_week + ' of ' + metadata.league_year + ':',
            'attachments': []
        }

        # for each submitted prediction that week
        for prediction in mongo.db.predictions.find({ 'year': metadata.league_year, 'week': metadata.league_week }):
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
    def get(self):
        return GetSubmittedPredictions.post(self)

def is_button_selected(element):
    return (element['type'] == 'button' and 'style' in element and element['style'] == 'primary'
            and element['name'] != 'score_submission')

def is_dropdown_selected(element):
    return element['type'] == 'select' and 'selected_options' in element

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

def build_dialog(payload):
    return {
        'callback_id': payload['callback_id'],
        'title': 'Score Predictions',
        'submit_label': 'Submit',
        # state is the best way to pass internal data to the dialog;
        # in this case, I'm passing the message_ts so the original message can be updated
        'state': payload['message_ts'],
        'elements': [
            {
                'type': 'text',
                'subtype': 'number',
                'label': 'High Score',
                'name': 'high_score'
            },
            {
                'type': 'text',
                'subtype': 'number',
                'label': 'Low Score',
                'name': 'low_score'
            }
        ]
    }

# This is how the sausage is made. This code is pretty boring, but it lays out pretty explicitly
# the JSON that makes up the prediction form. See the "interactive message" docs for more details:
# https://api.slack.com/interactive-messages
@api.route('/prediction/form/')
class SendPredictionForm(restful.Resource):
    def post(self):
        # since it's a direct Slack command, you'll need to respond with an error message
        if datetime.now() > metadata.deadline_time:
            return Response('Prediction forms cannot be sent before the start of the next week.')

        # if anyone has submitted a prediction for the week, that means we've sent a form already;
        # block any second form (if it's really necessary, it'll require a programmer to circumvent)
        if list(mongo.db.predictions.find({ 'year': metadata.league_year, 'week': metadata.league_week })):
            return Response('Prediction forms cannot be sent after a prediction has been submitted this week.')

        message = {
            'text': 'Make your predictions for week ' + metadata.league_week + ' matchups below by ' + metadata.deadline_string + ':',
            'attachments': []
        }
        # seemed like the best way to store the year and week inside the prediction form
        callback_id = metadata.league_year + '-' + metadata.league_week

        for index, matchup in enumerate(metadata.matchups):
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

        matchup_dropdown_template = {
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
        for matchup in metadata.matchups:
            matchup_dropdown_template['actions'][0]['options'].append({
                'text': matchup['team_one'] + ' versus ' + matchup['team_two'],
                'value': matchup['team_one'] + ' versus ' + matchup['team_two']
            })
        message['attachments'].append(matchup_dropdown_template)

        # reuse our existing dropdown object for the rest
        dropdown = copy.deepcopy(matchup_dropdown_template)
        dropdown['text'] = 'Which matchup will have the closest score?'
        dropdown['fallback'] = 'Closest'
        dropdown['actions'][0]['name'] = 'closest'
        message['attachments'].append(dropdown)

        # highest/lowest dropdowns should list teams, not matchups
        member_dropdown_template = copy.deepcopy(matchup_dropdown_template)
        member_dropdown_template['actions'][0]['text'] = 'Pick a team...'
        member_dropdown_template['actions'][0]['options'] = [ { 'text': name, 'value': name } for name in metadata.prediction_eligible_members ]

        dropdown = copy.deepcopy(member_dropdown_template)
        dropdown['text'] = 'Who will be the highest scorer?'
        dropdown['fallback'] = 'Highest'
        dropdown['actions'][0]['name'] = 'highest'
        message['attachments'].append(dropdown)

        dropdown = copy.deepcopy(member_dropdown_template)
        dropdown['text'] = 'Who will be the lowest scorer?'
        dropdown['fallback'] = 'Lowest'
        dropdown['actions'][0]['name'] = 'lowest'
        message['attachments'].append(dropdown)

        message['attachments'].append({
            'text': ':x: No submission for high/low score yet',
            'attachment_type': 'default',
            'callback_id': callback_id,
            'actions': [
                {
                    'name': 'score_submission',
                    'text': 'Enter Scores',
                    'type': 'button',
                    'value': 'score_submission'
                }
            ]
        })

        # defined in __init__.py
        post_to_slack(message)

        return
    def get(self):
        return SendPredictionForm.post(self)

# WARNING - I saved the most complicated code for the end. Don't skip the comment at the top!
@api.route('/prediction/calculations/')
class CalculatePredictions(restful.Resource):
    def post(self):
        metadata.invalidate_cached_week()

        # since it's a direct Slack command, you'll need to respond with an error message
        # can't calculate predictions for the week before in the first week
        # in practice, __init__.py checks for the latest week to start
        if metadata.league_week == '1':
            return Response('Prediction calculations are not available until the morning (8am) after Monday Night Football.')

        message = {
            'response_type': 'in_channel',
            'text': 'Prediction calculations for week ' + metadata.last_league_week + ' of ' + metadata.league_year + ':',
            'attachments': []
        }
        # we currently store ESPN matchup results by triggering a Slack command;
        # see scoreboard.py and the '/scoreboard/matchupresults/' endpoint for more details
        matchup_result = mongo.db.matchup_results.find_one({ 'year': metadata.league_year, 'week': metadata.last_league_week })
        formula_by_user, prediction_winners, closest_to_pin_stats = build_prediction_stats(matchup_result)

        message['attachments'].append({ 'text': build_results_string(matchup_result, closest_to_pin_stats) })
        message['attachments'].append({ 'text': build_bonus_string(prediction_winners, closest_to_pin_stats, formula_by_user) })
        message['attachments'].append({ 'text': build_formula_string(formula_by_user) })

        # first update the standings, then print the results
        update_prediction_standings(formula_by_user)
        message['attachments'].append({ 'text': build_standings_string() })

        return message
    def get(self):
        return CalculatePredictions.post(self)

def build_results_string(result, stats):
    results_string = 'Winners: ' + ', '.join(result['winners']) + '\n'
    results_string += 'Blowout: ' + stats['blowout_matchup']
    results_string += ' | Closest: ' + stats['closest_matchup'] + '\n'
    results_string += 'Highest: ' + result['highest'] + ', ' + result['high_score'] + ' | '
    results_string += 'Lowest: ' + result['lowest'] + ', ' + result['low_score']
    return results_string

def build_bonus_string(winners, stats, formula_by_user):
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
    highest_pin_winners = stats['highest_pin_winners']
    if highest_pin_winners:
        for winner in highest_pin_winners:
            formula_by_user[winner]['highest_bonus'] += 1
        bonus_string += ', with ' + ', '.join(highest_pin_winners[:-2] + [' and '.join(highest_pin_winners[-2:])])
        bonus_string += ' getting an extra point for guessing the highest score'
    winners_within_one_point = stats['highest_within_one_point'];
    if winners_within_one_point:
        for winner in winners_within_one_point:
            formula_by_user[winner]['highest_bonus'] += 1
        bonus_string += '. ' + ', '.join(winners_within_one_point[:-2] + [' and '.join(winners_within_one_point[-2:])])
        bonus_string += ' got a third point for guessing the score within a point'
    bonus_string += '.\n'

    if not winners['lowest']:
        bonus_string += 'No one'
    else:
        bonus_string += ', '.join(winners['lowest'][:-2] + [' and '.join(winners['lowest'][-2:])])
    bonus_string += ' got a point for guessing the lowest scorer'
    lowest_pin_winners = stats['lowest_pin_winners']
    if lowest_pin_winners:
        for winner in lowest_pin_winners:
            formula_by_user[winner]['lowest_bonus'] += 1
        bonus_string += ', with ' + ', '.join(lowest_pin_winners[:-2] + [' and '.join(lowest_pin_winners[-2:])])
        bonus_string += ' getting an extra point for guessing the lowest score'
    winners_within_one_point = stats['lowest_within_one_point'];
    if winners_within_one_point:
        for winner in winners_within_one_point:
            formula_by_user[winner]['lowest_bonus'] += 1
        bonus_string += '. ' + ', '.join(winners_within_one_point[:-2] + [' and '.join(winners_within_one_point[-2:])])
        bonus_string += ' got a third point for guessing the score within a point'
    bonus_string += '.\n'

    return bonus_string

def build_formula_string(formula_by_user):
    formula_string = 'TOTAL = MATCHUP TOTAL + BLOWOUT BONUS + CLOSEST BONUS + HIGHEST BONUS + LOWEST BONUS\n'
    user_formulas = sorted(formula_by_user.values(), key=PREDICTION_FORMULA, reverse=True)
    for user_formula in user_formulas:
        formula_total = PREDICTION_FORMULA(user_formula)
        formula_string += user_formula['username'] + \
            ': ' + str(formula_total) + \
            ' = ' + str(user_formula['matchup_total']) + \
            ' + ' + str(user_formula['blowout_bonus']) + \
            ' + ' + str(user_formula['closest_bonus']) + \
            ' + ' + str(user_formula['highest_bonus']) + \
            ' + ' + str(user_formula['lowest_bonus']) + '\n'
    return formula_string

def build_standings_string():
    standings = mongo.db.prediction_standings.find({ 'year': metadata.league_year, 'week': metadata.last_league_week }).sort(
        # see scoreboard.py and the '/scoreboard/tiebreakers/' for a command
        # that factors in tiebreakers when sorting waiver order standings
        [('total', -1)])
    standings_string = 'Draft selection standings for the season so far:\n'
    for prediction_record in standings:
        standings_string += prediction_record['username'] + ' - ' + str(prediction_record['total']) + '\n'
    return standings_string

def build_prediction_stats(result):
    formula_by_user = {}
    winners = {
        'matchup': [],
        'blowout': [],
        'closest': [],
        'highest': [],
        'lowest': []
    }
    stats = {
        'blowout_matchup': result['blowout_matchup'],
        'closest_matchup': result['closest_matchup'],
        'highest_pin_winners': [],
        'highest_pin_score': '',
        'highest_within_one_point': [],
        'lowest_pin_winners': [],
        'lowest_pin_score': '',
        'lowest_within_one_point': []
    }
    actual_winners = result['winners']
    for prediction in mongo.db.predictions.find({ 'year': metadata.league_year, 'week': metadata.last_league_week }):
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
                stats['highest_pin_winners'], stats['highest_pin_score'], stats['highest_within_one_point'] = (
                    set_closest_to_pin_variables(username, prediction['high_score'], result['high_score'], stats['highest_pin_winners'], stats['highest_pin_score'], stats['highest_within_one_point']))

        winners['lowest'] += [username
            for g in form_groups for element in g['actions']
            if is_lowest_predicted(element, g, result)]
        if username in winners['lowest']:
            user_formula['lowest_bonus'] += 1
            if 'low_score' in prediction:
                stats['lowest_pin_winners'], stats['lowest_pin_score'], stats['lowest_within_one_point'] = (
                    set_closest_to_pin_variables(username, prediction['low_score'], result['low_score'], stats['lowest_pin_winners'], stats['lowest_pin_score'], stats['lowest_within_one_point']))

        # after processing all this user's selections
        formula_by_user[username] = user_formula
    return (formula_by_user, winners, stats)

def is_blowout_selected(element, form_group):
    return element['type'] == 'select' and 'blowout' in form_group['text'] and 'selected_options' in element

def is_blowout_winner_predicted(element, form_group, result, winners):
    if is_blowout_selected(element, form_group):
        selected = element['selected_options'][0]
        return result['blowout'] in selected['text'] and result['blowout'] in winners
    return False

def is_closest_selected(element, form_group):
    return element['type'] == 'select' and 'closest' in form_group['text'] and 'selected_options' in element

def is_closest_predicted(element, form_group, result):
    if is_closest_selected(element, form_group):
        selected = element['selected_options'][0]
        return result['closest'] in selected['text']
    return False

def is_highest_selected(element, form_group):
    return element['type'] == 'select' and 'highest' in form_group['text'] and 'selected_options' in element

def is_highest_predicted(element, form_group, result):
    if is_highest_selected(element, form_group):
        selected = element['selected_options'][0]
        return result['highest'] in selected['text']
    return False

def is_lowest_selected(element, form_group):
    return element['type'] == 'select' and 'lowest' in form_group['text'] and 'selected_options' in element

def is_lowest_predicted(element, form_group, result):
    if is_lowest_selected(element, form_group):
        selected = element['selected_options'][0]
        return result['lowest'] in selected['text']
    return False

def set_closest_to_pin_variables(candidate_winner, candidate_score, actual_score, current_winners, current_closest_score, current_winners_within_one_point):
    candidate_score_decimal = Decimal(candidate_score)
    actual_score_decimal = Decimal(actual_score)
    candidate_distance_to_pin = abs(candidate_score_decimal - actual_score_decimal)
    if candidate_distance_to_pin <= 1:
        current_winners_within_one_point.append(candidate_winner)

    if current_winners and current_closest_score:
        current_closest_decimal = Decimal(current_closest_score)
        current_distance_to_pin = abs(current_closest_decimal - actual_score_decimal)
        # rules conference says we should support ties, make it so
        if current_distance_to_pin == candidate_distance_to_pin:
            current_winners.append(candidate_winner)
            return (current_winners, current_closest_score, current_winners_within_one_point)
        elif current_distance_to_pin > candidate_distance_to_pin:
            return ([candidate_winner], candidate_score, current_winners_within_one_point)
        else:
            return (current_winners, current_closest_score, current_winners_within_one_point)
    # no highest/lowest recorded so far? you're the winner by default
    return ([candidate_winner], candidate_score, current_winners_within_one_point)

def update_prediction_standings(formula_by_user):
    if int(metadata.last_league_week) == 1:
        # put zeroes there for anyone who missed the first prediction
        # VERY IMPORTANT, cause we assume every league member has a row in this table
        users_without_predictions = list(set(metadata.usernames) - set(formula_by_user.keys()))
        for username in users_without_predictions:
            database_key = { 'username': username, 'year': metadata.league_year, 'week': metadata.last_league_week }
            mongo.db.prediction_standings.update_one(database_key, {
                '$set': {
                    'total': 0
                },
            }, upsert=True)
        # loop through everyone who submitted a prediction this week
        for user_formula in formula_by_user.values():
            formula_total = PREDICTION_FORMULA(user_formula)
            database_key = { 'username': user_formula['username'], 'year': metadata.league_year, 'week': metadata.last_league_week }
            # standings on the first week is trivial and exactly the same as waiver order standings
            mongo.db.prediction_standings.update_one(database_key, {
                '$set': {
                    'total': formula_total
                },
            }, upsert=True)

    if int(metadata.last_league_week) > 1:
        week_before = str(int(metadata.last_league_week) - 1)
        week_before_standings = mongo.db.prediction_standings.find({ 'year': metadata.league_year, 'week': week_before })
        for prediction_record in week_before_standings:
            username = prediction_record['username']
            database_key = { 'username': username, 'year': metadata.league_year, 'week': metadata.last_league_week }

            if username in formula_by_user:
                formula_total = PREDICTION_FORMULA(formula_by_user[username])
            else:
                formula_total = 0

            mongo.db.prediction_standings.update_one(database_key, {
                '$set': {
                    'total': prediction_record['total'] + formula_total
                },
            }, upsert=True)
    return
