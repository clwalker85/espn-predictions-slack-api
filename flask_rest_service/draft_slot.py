import os
import json
import requests
from datetime import datetime
from flask import request, abort, Response
from flask.ext import restful
# see __init__.py for these definitions
from flask_rest_service import app, api, mongo, post_to_slack, LEAGUE_ID, LEAGUE_MEMBERS, LEAGUE_USERNAMES, LEAGUE_YEAR, LEAGUE_WEEK, LAST_LEAGUE_WEEK, DEADLINE_STRING, DEADLINE_TIME, MATCHUPS, PREDICTION_ELIGIBLE_MEMBERS

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

# This is how the sausage is made. This code is pretty boring, but it lays out pretty explicitly
# the JSON that makes up the selection form. See the "interactive message" docs for more details:
# https://api.slack.com/interactive-messages
@api.route('/draft/form/')
class SendPredictionForm(restful.Resource):
    def post(self):
        # since it's a direct Slack command, you'll need to respond with an error message
        if datetime.now() > DEADLINE_TIME:
            return Response('Prediction forms cannot be sent before the start of the next week.')

        # if anyone has submitted a prediction for the week, that means we've sent a form already
        # block any second form (if it's really necessary, it'll require a programmer to circumvent)
        if list(mongo.db.predictions.find({ 'year': LEAGUE_YEAR, 'week': LEAGUE_WEEK })):
            return Response('Prediction forms cannot be sent after a prediction has been submitted this week.')

        message = {
            'text': 'Make your predictions for week ' + LEAGUE_WEEK + ' matchups below by ' + DEADLINE_STRING + ':',
            'attachments': []
        }
        # seemed like the best way to store the year and week inside the prediction form
        callback_id = LEAGUE_YEAR + '-' + LEAGUE_WEEK

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

        # defined in __init__.py
        post_to_slack(message)

        return
