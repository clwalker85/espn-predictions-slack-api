import copy
import os
import json
import math
import pprint
import random
import requests
from collections import defaultdict
from decimal import Decimal
from datetime import datetime
from espn_api.football import League
from flask import request, abort, Response
#from flask.ext import restful
import flask_restful as restful
# see __init__.py for these definitions
from flask_rest_service import app, api, mongo, refresh_week_constants, post_to_slack, open_dialog, update_message, LEAGUE_ID, LEAGUE_MEMBERS, LEAGUE_USERNAMES, LEAGUE_YEAR, LEAGUE_WEEK, LAST_LEAGUE_WEEK, DEADLINE_STRING, DEADLINE_TIME, MATCHUPS, PREDICTION_ELIGIBLE_MEMBERS, ESPN_SWID, ESPN_S2

@api.route('/history/headtohead/')
class HeadToHeadHistory(restful.Resource):
    def post(self):
        message = {
            'response_type': 'in_channel',
            'text': 'All-time head-to-head history for week ' + LEAGUE_WEEK + ' matchups:',
            'attachments': []
        }

        for index, matchup in enumerate(MATCHUPS):
            manager_one = matchup['team_one']
            manager_two = matchup['team_two']

            # this matches co-owners stored as an array, too
            manager_one_reg_season_query = mongo.db.scores_per_matchup.find(
                { 'winner': manager_one, 'loser': manager_two, 'playoffs': False })
            manager_one_reg_season_list = list(manager_one_reg_season_query)
            manager_one_reg_season_wins = len(manager_one_reg_season_list)
            manager_one_playoff_query = mongo.db.scores_per_matchup.find(
                { 'winner': manager_one, 'loser': manager_two, 'playoffs': True, 'consolation': False })
            manager_one_playoff_list = list(manager_one_playoff_query)
            manager_one_playoff_wins = len(manager_one_playoff_list)
            manager_one_consolation_query = mongo.db.scores_per_matchup.find(
                { 'winner': manager_one, 'loser': manager_two, 'playoffs': True, 'consolation': True })
            manager_one_consolation_list = list(manager_one_consolation_query)
            manager_one_consolation_wins = len(manager_one_consolation_list)

            manager_two_reg_season_query = mongo.db.scores_per_matchup.find(
                { 'winner': manager_two, 'loser': manager_one, 'playoffs': False })
            manager_two_reg_season_list = list(manager_two_reg_season_query)
            manager_two_reg_season_wins = len(manager_two_reg_season_list)
            manager_two_playoff_query = mongo.db.scores_per_matchup.find(
                { 'winner': manager_two, 'loser': manager_one, 'playoffs': True, 'consolation': False })
            manager_two_playoff_list = list(manager_two_playoff_query)
            manager_two_playoff_wins = len(manager_two_playoff_list)
            manager_two_consolation_query = mongo.db.scores_per_matchup.find(
                { 'winner': manager_two, 'loser': manager_one, 'playoffs': True, 'consolation': True })
            manager_two_consolation_list = list(manager_two_consolation_query)
            manager_two_consolation_wins = len(manager_two_consolation_list)

            matchup_string = ''

            if manager_one_reg_season_wins > manager_two_reg_season_wins:
                matchup_string += manager_one + ' ' + str(manager_one_reg_season_wins) + '-' + str(manager_two_reg_season_wins) + ' ' + manager_two
            else:
                matchup_string += manager_two + ' ' + str(manager_two_reg_season_wins) + '-' + str(manager_one_reg_season_wins) + ' ' + manager_one

            # loop backwards through time to track winning streak
            if (manager_one_reg_season_wins + manager_two_reg_season_wins) > 0:
                reg_season_list = manager_one_reg_season_list + manager_two_reg_season_list
                reg_season_list.sort(key=lambda x: x['year'], reverse=True)

                last_manager_to_win = None
                number_of_wins_in_streak = 0
                for m in reg_season_list:
                    if last_manager_to_win == None:
                        last_manager_to_win = m['winner']
                    if m['winner'] != last_manager_to_win:
                        break
                    number_of_wins_in_streak += 1

                if (number_of_wins_in_streak == 1):
                    matchup_string += " (last regular season game won by "
                else:
                    matchup_string += " (last " + str(number_of_wins_in_streak) + " regular season games won by "

                if last_manager_to_win == manager_one:
                    matchup_string += manager_one + ")"
                else:
                    matchup_string += manager_two + ")"

            if (manager_one_playoff_wins + manager_two_playoff_wins) > 0:
                # keep same order as regular season record
                if manager_one_reg_season_wins > manager_two_reg_season_wins:
                    matchup_string += '\n- ' + str(manager_one_playoff_wins) + '-' + str(manager_two_playoff_wins) + ' in playoffs'
                else:
                    matchup_string += '\n- ' + str(manager_two_playoff_wins) + '-' + str(manager_one_playoff_wins) + ' in playoffs'
                playoff_years_list = manager_one_playoff_list + manager_two_playoff_list
                matchup_string += ' (' + ', '.join(build_playoff_history_string(m) for m in playoff_years_list) + ')'

            if (manager_one_consolation_wins + manager_two_consolation_wins) > 0:
                # keep same order as regular season record
                if manager_one_reg_season_wins > manager_two_reg_season_wins:
                    matchup_string += '\n- ' + str(manager_one_consolation_wins) + '-' + str(manager_two_consolation_wins) + ' in consolation'
                else:
                    matchup_string += '\n- ' + str(manager_two_consolation_wins) + '-' + str(manager_one_consolation_wins) + ' in consolation'
                consolation_years_list = manager_one_consolation_list + manager_two_consolation_list
                matchup_string += ' (' + ', '.join(build_consolation_history_string(m) for m in consolation_years_list) + ')'

            # one message attachment per matchup
            message['attachments'].append({ 'text': matchup_string })

        return message
    def get(self):
        return HeadToHeadHistory.post(self)

def build_playoff_history_string(matchup):
    return str(matchup['year']) + playoff_detail(matchup)

def playoff_detail(matchup):
    if matchup['quarterfinals']:
        return " quarterfinals"
    elif matchup['semifinals']:
        return " semifinals"
    elif matchup['finals']:
        if matchup['championship']:
            return " championship"
        if matchup['third_place']:
            return " third place game"
        return ""
    else:
        return ""

def build_consolation_history_string(element):
    return str(element['year']) + consolation_detail(element)

def consolation_detail(element):
    return " breckfast bowl" if element['finals'] else ""

@api.route('/history/podium/')
class Podium(restful.Resource):
    def post(self):
        message = {
            'response_type': 'in_channel',
            'text': 'Podium finish for every league year:',
            'attachments': []
        }

        championship_query = mongo.db.scores_per_matchup.find({ 'consolation': False, 'championship': True, 'third_place': False })
        championship_list = list(championship_query)
        third_place_query = mongo.db.scores_per_matchup.find({ 'consolation': False, 'championship': False, 'third_place': True })
        third_place_list = list(third_place_query)
        podium_list = championship_list + third_place_list

        podium_string = ''
        for m in sorted(podium_list, key=lambda t: (-t['year'], -t['championship'])):
            if m['championship']:
                podium_string += str(m['year']) + ' CHAMPION: ' + m['winner'] + ' (' + str(m['winning_score']) + ')'
                podium_string += ', 2nd: ' + m['loser'] + ' (' + str(m['losing_score']) + ')'
            elif m['third_place']:
                podium_string += ', 3rd: ' + m['winner'] + '\n'

        message['attachments'].append({ 'text': podium_string })
        return message
    def get(self):
        return Podium.post(self)

@api.route('/history/lastplace/')
class LastPlace(restful.Resource):
    def post(self):
        message = {
            'response_type': 'in_channel',
            'text': 'Breckfast Bowl loser for every league year:',
            'attachments': []
        }

        last_place_query = mongo.db.scores_per_matchup.find({ 'consolation': True, 'championship': True })
        last_place_list = list(last_place_query)

        last_place_string = ''
        for m in sorted(last_place_list, key=lambda t: -t['year']):
            last_place_string += str(m['year']) + ': ' + m['loser'] + '\n'

        message['attachments'].append({ 'text': last_place_string })
        return message
    def get(self):
        return LastPlace.post(self)

@api.route('/history/winnings/')
class Winnings(restful.Resource):
    def post(self):
        message = {
            'response_type': 'in_channel',
            'text': 'Cash Winnings Leaderboard:',
            'attachments': []
        }

        championship_query = mongo.db.scores_per_matchup.find({ 'consolation': False, 'championship': True, 'third_place': False })
        championship_list = list(championship_query)
        third_place_query = mongo.db.scores_per_matchup.find({ 'consolation': False, 'championship': False, 'third_place': True })
        third_place_list = list(third_place_query)
        podium_list = championship_list + third_place_list

        standings = defaultdict(int)
        for m in podium_list:
            dues_per_member = 20
            if m['year'] > 2013:
                dues_per_member = 30
            if m['year'] > 2018:
                dues_per_member = 50

            # TODO - base members off mongo.db.league_metadata.members
            members = 14
            if m['year'] > 2019:
                members = 10
            if m['year'] == 2021:
                members = 12

            if m['championship']:
                champ = m['winner']
                if m['year'] > 2019:
                    standings[champ] += dues_per_member * (members - 3)
                else:
                    standings[champ] += dues_per_member * (members - 4)

                runner_up = m['loser']
                if m['year'] > 2019:
                    standings[runner_up] += dues_per_member * 2
                else:
                    standings[runner_up] += dues_per_member * 3
            elif m['third_place']:
                third = m['winner']
                standings[third] += dues_per_member

        winnings_string = ''
        for player, money in sorted(standings.items(), key=lambda item: -item[1]):
            years_in_league = mongo.db.scores_per_matchup.distinct('year', { '$or': [ {'winner': player}, {'loser': player} ] })
            dues = 0
            for year in years_in_league:
                if year > 2018:
                    dues += 50
                elif year > 2013:
                    dues += 30
                else:
                    dues += 20
            winnings_string += player + ': $' + str(money) + ' ($' + str(dues) + ' dues paid, $' + str(money - dues) + ' net winnings)\n'

        message['attachments'].append({ 'text': winnings_string })
        return message
    def get(self):
        return Winnings.post(self)
