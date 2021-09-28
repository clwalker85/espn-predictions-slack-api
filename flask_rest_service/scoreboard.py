import os
import json
import math
import pprint
import requests
from decimal import Decimal
from datetime import datetime
from espn_api.football import League
from flask import request, abort, Response
from flask.ext import restful
# see __init__.py for these definitions
from flask_rest_service import app, api, mongo, post_to_slack, open_dialog, update_message, LEAGUE_ID, LEAGUE_MEMBERS, LEAGUE_USERNAMES, LEAGUE_YEAR, LEAGUE_WEEK, LAST_LEAGUE_WEEK, DEADLINE_STRING, DEADLINE_TIME, MATCHUPS, PREDICTION_ELIGIBLE_MEMBERS, ESPN_SWID, ESPN_S2

# simple proof of concept that I could get Mongo working in Heroku
@api.route('/')
class Root(restful.Resource):
    def get(self):
        return {
            'status': 'OK',
            'mongo': str(mongo.db),
        }

@api.route('/scoreboard/')
class Scoreboard(restful.Resource):
    def post(self):
        # for direct Slack commands, you don't get a payload like an interactive message action,
        # you have to parse the text of the parameters
        #text = request.form.get('text', None)
        #param = text.split()
        #query_type = param[0]

        #if query_type == 'help':
        #message['attachments'].append({ 'text': prediction_string })

        message = {
            'response_type': 'in_channel',
            'text': '',
            'attachments': []
        }

        # show last week until projections are due and week hasn't officially ended
        week_shown = LAST_LEAGUE_WEEK
        if datetime.now() > DEADLINE_TIME:
            week_shown = LEAGUE_WEEK

        # TODO - prefetch player_metadata in __init__.py (like MATCHUPS)
        player_lookup_by_espn_name = {}
        for p in mongo.db.player_metadata.find():
            if p['espn_owner_name']:
                player_lookup_by_espn_name[p['espn_owner_name']] = p

        matchups = []
        league = League(league_id=int(LEAGUE_ID), year=int(LEAGUE_YEAR), espn_s2=ESPN_S2, swid=ESPN_SWID)
        box_scores = league.box_scores(int(week_shown))
        for s in box_scores:
            home_name = player_lookup_by_espn_name[s.home_team.owner]['display_name']
            matchup_string = home_name + ' - ' + str(s.home_score)
            if (s.home_projected != -1 and not math.isclose(s.home_score, s.home_projected, abs_tol=0.01)):
                matchup_string += ' (' + str(s.home_projected) + ')'

            away_name = player_lookup_by_espn_name[s.away_team.owner]['display_name']
            matchup_string += ' versus ' + away_name + ' - ' + str(s.away_score)
            if (s.away_projected != -1 and not math.isclose(s.away_score, s.away_projected, abs_tol=0.01)):
                matchup_string += ' (' + str(s.away_projected) + ')'

            message['attachments'].append({ 'text': matchup_string })

            winner = player_lookup_by_espn_name[s.home_team.owner]['player_id']
            loser = player_lookup_by_espn_name[s.away_team.owner]['player_id']
            winning_score = s.home_score
            losing_score = s.away_score
            if (s.away_score > s.home_score):
                winner = player_lookup_by_espn_name[s.away_team.owner]['player_id']
                loser = player_lookup_by_espn_name[s.home_team.owner]['player_id']
                winning_score = s.away_score
                losing_score = s.home_score

            matchups.append({
                'winner': winner,
                'loser': loser,
                'winning_score': winning_score,
                'losing_score': losing_score
                # TODO - Find out how to set playoff-specific flags based on ESPN API data
            })

        # TODO - there's a mix of string and int types stored for years and weeks, pick one (probably int)
        database_key = { 'year': int(LEAGUE_YEAR), 'week': int(week_shown) }
        mongo.db.scores.update(database_key, {
            '$set': {
                'year': int(LEAGUE_YEAR),
                'week': int(week_shown),
                'matchups': matchups,
                # TODO - Find out how to set these flags based on ESPN API data
                'playoffs': False,
                'quarterfinals': False,
                'semifinals': False,
                'finals': False,
            },
        # insert if you need to, and make sure to guarantee one record per year/week
        }, upsert=True, multi=False)

        #app.logger.debug("metadata")
        return message

@api.route('/scoreboard/matchupresults/')
class MatchupResults(restful.Resource):
    def post(self):
        # can't calculate matchup results for the week before in the first week
        # in practice, __init__.py checks for the latest week to start
        if LEAGUE_WEEK == '1':
            return Response('Matchup result calculations are not available until the morning (8am) after Monday Night Football.')

        # TODO - return error if no scores are found
        # TODO - there's a mix of string and int types stored for years and weeks, pick one (probably int)
        scores_result = mongo.db.scores.find_one({ 'year': int(LEAGUE_YEAR), 'week': int(LAST_LEAGUE_WEEK) })
        # TODO - prefetch player_metadata in __init__.py (like MATCHUPS)
        player_lookup_by_id = {}
        for p in mongo.db.player_metadata.find():
            player_lookup_by_id[p['player_id']] = p

        winners = []
        blowout_matchup_winner, blowout_matchup = '', ''
        closest_matchup_winner, closest_matchup = '', ''
        biggest_margin, smallest_margin = 0, 9999
        highest_scorer, lowest_scorer = '', ''
        high_score, low_score = 0, 9999

        for matchup in scores_result['matchups']:
            margin = matchup['winning_score'] - matchup['losing_score']
            winner_name = player_lookup_by_id[matchup['winner']]['display_name']
            loser_name = player_lookup_by_id[matchup['loser']]['display_name']

            winners.append(winner_name)

            if matchup['winning_score'] > high_score:
                high_score = matchup['winning_score']
                highest_scorer = winner_name

            if matchup['losing_score'] < low_score:
                low_score = matchup['losing_score']
                lowest_scorer = loser_name

            if margin > biggest_margin:
                biggest_margin = margin
                blowout_matchup_winner = winner_name
                # HACK - would be a pain to make LAST_WEEK_MATCHUPS just to order the names right;
                # this should not affect logic and only be for display purposes
                blowout_matchup = winner_name + " versus " + loser_name

            if margin < smallest_margin:
                smallest_margin = margin
                closest_matchup_winner = winner_name
                # HACK - would be a pain to make LAST_WEEK_MATCHUPS just to order the names right;
                # this should not affect logic and only be for display purposes
                closest_matchup = winner_name + " versus " + loser_name

        # TODO - there's a mix of string and int types stored for years and weeks, pick one (probably int)
        database_key = { 'year': LEAGUE_YEAR, 'week': LAST_LEAGUE_WEEK }
        mongo.db.matchup_results.update(database_key, {
            '$set': {
                'winners': winners,
                'blowout': blowout_matchup_winner,
                'blowout_matchup': blowout_matchup,
                'closest': closest_matchup_winner,
                'closest_matchup': closest_matchup,
                'highest': highest_scorer,
                'lowest': lowest_scorer,
                'high_score': str(high_score),
                'low_score': str(low_score),
                'year': LEAGUE_YEAR,
                'week': LAST_LEAGUE_WEEK
            },
        # insert if you need to, and make sure to guarantee one record per year/week
        }, upsert=True, multi=False)

        results_string = 'Matchup calculations for week ' + LAST_LEAGUE_WEEK + ' of ' + LEAGUE_YEAR + ':\n'
        results_string += 'Winners: ' + ', '.join(winners) + '\n'
        results_string += 'Blowout: ' + blowout_matchup
        results_string += ' | Closest: ' + closest_matchup + '\n'
        results_string += 'Highest: ' + highest_scorer + ', ' + str(high_score) + ' | '
        results_string += 'Lowest: ' + lowest_scorer + ', ' + str(low_score)

        return Response(results_string)

@api.route('/scoreboard/headtohead/')
class HeadToHeadHistory(restful.Resource):
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
            manager_ids = [manager_one_id, manager_two_id]

            # this matches co-owners stored as an array, too
            # TODO - this code looks like ass, reuse a dictionary we modify over and over for the filters below
            manager_one_reg_season_query = mongo.db.scores.find({ '$and': [
                { 'matchups':
                    { '$elemMatch': {
                        'winner': manager_one_id,
                        'loser': manager_two_id
                    } }
                }, { 'playoffs': False } ] })
            manager_one_reg_season_wins = manager_one_reg_season_query.count()
            manager_one_playoff_query = mongo.db.scores.find({ '$and': [
                { 'matchups':
                    { '$elemMatch': {
                        'winner': manager_one_id,
                        'loser': manager_two_id,
                        'consolation': { '$in': [ None, False ] }
                    } }
                }, { 'playoffs': True } ] })
            manager_one_playoff_wins = manager_one_playoff_query.count()
            manager_one_consolation_query = mongo.db.scores.find({ '$and': [
                { 'matchups':
                    { '$elemMatch': {
                        'winner': manager_one_id,
                        'loser': manager_two_id,
                        'consolation': True
                    } }
                }, { 'playoffs': True } ] })
            manager_one_consolation_wins = manager_one_consolation_query.count()

            manager_two_reg_season_query = mongo.db.scores.find({ '$and': [
                { 'matchups':
                    { '$elemMatch': {
                        'winner': manager_two_id,
                        'loser': manager_one_id
                    } }
                }, { 'playoffs': False } ] })
            manager_two_reg_season_wins = manager_two_reg_season_query.count()
            manager_two_playoff_query = mongo.db.scores.find({ '$and': [
                { 'matchups':
                    { '$elemMatch': {
                        'winner': manager_two_id,
                        'loser': manager_one_id,
                        'consolation': { '$in': [ None, False ] }
                    } }
                }, { 'playoffs': True } ] })
            manager_two_playoff_wins = manager_two_playoff_query.count()
            manager_two_consolation_query = mongo.db.scores.find({ '$and': [
                { 'matchups':
                    { '$elemMatch': {
                        'winner': manager_two_id,
                        'loser': manager_one_id,
                        'consolation': True
                    } }
                }, { 'playoffs': True } ] })
            manager_two_consolation_wins = manager_two_consolation_query.count()

            matchup_string = ''

            if manager_one_reg_season_wins > manager_two_reg_season_wins:
                matchup_string += manager_one + ' ' + str(manager_one_reg_season_wins) + '-' + str(manager_two_reg_season_wins) + ' ' + manager_two
            else:
                matchup_string += manager_two + ' ' + str(manager_two_reg_season_wins) + '-' + str(manager_one_reg_season_wins) + ' ' + manager_one

            # loop backwards through time to track winning streak
            if (manager_one_reg_season_wins + manager_two_reg_season_wins) > 0:
                reg_season_list = list(manager_one_reg_season_query) + list(manager_two_reg_season_query)
                reg_season_list.sort(key=lambda x: x['year'], reverse=True)

                last_manager_to_win = None
                number_of_wins_in_streak = 0
                for e in reg_season_list:
                    for m in e['matchups']:
                        if m['winner'] in manager_ids and m['loser'] in manager_ids:
                            if last_manager_to_win == None:
                                last_manager_to_win = m['winner']
                            if m['winner'] != last_manager_to_win:
                                break
                            number_of_wins_in_streak += 1
                    else:
                        continue
                    break

                if (number_of_wins_in_streak == 1):
                    matchup_string += " (last regular season game won by "
                else:
                    matchup_string += " (last " + str(number_of_wins_in_streak) + " regular season games won by "

                if last_manager_to_win == manager_one_id:
                    matchup_string += manager_one + ")"
                else:
                    matchup_string += manager_two + ")"

            if (manager_one_playoff_wins + manager_two_playoff_wins) > 0:
                # keep same order as regular season record
                if manager_one_reg_season_wins > manager_two_reg_season_wins:
                    matchup_string += '\n- ' + str(manager_one_playoff_wins) + '-' + str(manager_two_playoff_wins) + ' in playoffs'
                else:
                    matchup_string += '\n- ' + str(manager_two_playoff_wins) + '-' + str(manager_one_playoff_wins) + ' in playoffs'
                playoff_years_list = list(manager_one_playoff_query) + list(manager_two_playoff_query)
                matchup_string += ' (' + ', '.join(build_playoff_history_string(e, manager_ids) for e in playoff_years_list) + ')'

            if (manager_one_consolation_wins + manager_two_consolation_wins) > 0:
                # keep same order as regular season record
                if manager_one_reg_season_wins > manager_two_reg_season_wins:
                    matchup_string += '\n- ' + str(manager_one_consolation_wins) + '-' + str(manager_two_consolation_wins) + ' in consolation'
                else:
                    matchup_string += '\n- ' + str(manager_two_consolation_wins) + '-' + str(manager_one_consolation_wins) + ' in consolation'
                consolation_years_list = list(manager_one_consolation_query) + list(manager_two_consolation_query)
                matchup_string += ' (' + ', '.join(build_consolation_history_string(e) for e in consolation_years_list) + ')'

            # one message attachment per matchup
            message['attachments'].append({ 'text': matchup_string })

        return message

def build_playoff_history_string(element, manager_ids):
    return str(element['year']) + playoff_detail(element, manager_ids)

def playoff_detail(element, manager_ids):
    if element['quarterfinals']:
        return " quarterfinals"
    elif element['semifinals']:
        return " semifinals"
    elif element['finals']:
        for m in element['matchups']:
            if m['winner'] in manager_ids and m['loser'] in manager_ids:
                if m['championship']:
                    return " championship"
                if m['third_place']:
                    return " third place game"
        return ""
    else:
        return ""

def build_consolation_history_string(element):
    return str(element['year']) + consolation_detail(element)

def consolation_detail(element):
    return " breckfast bowl" if element['finals'] else ""
