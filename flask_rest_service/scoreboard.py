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
from flask_rest_service import app, api, mongo, post_to_slack, open_dialog, update_message, LEAGUE_ID, LEAGUE_MEMBERS, LEAGUE_USERNAMES, LEAGUE_YEAR, LEAGUE_WEEK, LAST_LEAGUE_WEEK, DEADLINE_STRING, DEADLINE_TIME, MATCHUPS, PREDICTION_ELIGIBLE_MEMBERS

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

@api.route('/scoreboard/headtohead/')
class GetHeadToHeadHistory(restful.Resource):
    def post(self):
        message = {
            'response_type': 'in_channel',
            'text': 'All-time head-to-head history for week ' + LEAGUE_WEEK + ' matchups:',
            'attachments': []
        }

        for index, matchup in enumerate(MATCHUPS):
            manager_one = matchup['team_one']
            # HACK - mapping display_name to player_id is not ideal;
            # joins are not ideal in a non-relational DB either, so maybe we store both everywhere
            # TODO - prefetch player_metadata in __init__.py (like MATCHUPS)
            manager_one_metadata = mongo.db.player_metadata.find_one({ 'display_name': manager_one})
            manager_one_id = manager_one_metadata['player_id']
            manager_two = matchup['team_two']
            manager_two_metadata = mongo.db.player_metadata.find_one({ 'display_name': manager_two})
            manager_two_id = manager_two_metadata['player_id']

            # this matches co-owners stored as an array, too
            # TODO - reuse a dictionary we modify over and over for the filters below
            manager_one_reg_season_wins = mongo.db.scores.find({ 'matchups': { '$elemMatch': {
                    'winner': manager_one_id,
                    'loser': manager_two_id,
                }, 'playoffs': False } }).count()
            manager_one_playoff_wins = mongo.db.scores.find({ 'matchups': { '$elemMatch': {
                    'winner': manager_one_id,
                    'loser': manager_two_id,
                    'consolation': { '$in': [ null, False ] }
                }, 'playoffs': True } }).count()
            manager_one_consolation_wins = mongo.db.scores.find({ 'matchups': { '$elemMatch': {
                    'winner': manager_one_id,
                    'loser': manager_two_id,
                    'consolation': True
                }, 'playoffs': True } }).count()

            manager_two_reg_season_wins = mongo.db.scores.find({ 'matchups': { '$elemMatch': {
                    'winner': manager_two_id,
                    'loser': manager_one_id
                }, 'playoffs': False } }).count()
            manager_two_playoff_wins = mongo.db.scores.find({ 'matchups': { '$elemMatch': {
                    'winner': manager_two_id,
                    'loser': manager_one_id,
                    'consolation': { '$in': [ null, False ] }
                }, 'playoffs': True } }).count()
            manager_two_consolation_wins = mongo.db.scores.find({ 'matchups': { '$elemMatch': {
                    'winner': manager_two_id,
                    'loser': manager_one_id,
                    'consolation': true
                }, 'playoffs': True } }).count()

            matchup_string = ''

            if manager_one_reg_season_wins > manager_two_reg_season_wins:
                matchup_string += manager_one + ' ' + str(manager_one_reg_season_wins) + '-' + str(manager_two_reg_season_wins) + ' ' + manager_two
            else:
                matchup_string += manager_two + ' ' + str(manager_two_reg_season_wins) + '-' + str(manager_one_reg_season_wins) + ' ' + manager_one

            if (manager_one_playoff_wins + manager_two_playoff_wins) > 0:
                # keep same order as regular season record
                if manager_one_reg_season_wins > manager_two_reg_season_wins:
                    matchup_string += ', ' + str(manager_one_playoff_wins) + '-' + str(manager_two_playoff_wins) + 'in playoffs'
                else:
                    matchup_string += ', ' + str(manager_two_playoff_wins) + '-' + str(manager_one_playoff_wins) + 'in playoffs'

            if (manager_one_consolation_wins + manager_two_consolation_wins) > 0:
                # keep same order as regular season record
                if manager_one_reg_season_wins > manager_two_reg_season_wins:
                    matchup_string += ', ' + str(manager_one_consolation_wins) + '-' + manager_two_consolation_wins + 'in consolation'
                else:
                    matchup_string += ', ' + str(manager_two_consolation_wins) + '-' + manager_one_consolation_wins + 'in consolation'

            # one message attachment per matchup
            message['attachments'].append({ 'text': matchup_string })

        return message
