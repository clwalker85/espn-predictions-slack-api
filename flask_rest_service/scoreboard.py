import copy
import os
import json
import math
import pprint
import random
import requests
from decimal import Decimal
from datetime import datetime
from espn_api.football import League
from flask import request, abort, Response
#from flask.ext import restful
import flask_restful as restful
# see __init__.py for these definitions
from flask_rest_service import app, api, mongo, refresh_week_constants, post_to_slack, open_dialog, update_message, LEAGUE_ID, LEAGUE_MEMBERS, LEAGUE_USERNAMES, LEAGUE_YEAR, LEAGUE_WEEK, LAST_LEAGUE_WEEK, DEADLINE_STRING, DEADLINE_TIME, MATCHUPS, PREDICTION_ELIGIBLE_MEMBERS, ESPN_SWID, ESPN_S2

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
        week = int(week_shown)
        box_scores = league.box_scores(week)

        last_week_of_regular_season = league.settings.reg_season_count
        number_of_teams_in_league = league.settings.team_count
        number_of_playoff_teams = league.settings.playoff_team_count

        is_playoff = week > last_week_of_regular_season
        is_round_one = last_week_of_regular_season + 1 == week
        is_round_two = last_week_of_regular_season + 2 == week
        is_round_three = last_week_of_regular_season + 3 == week
        is_quarterfinals = number_of_playoff_teams > 4 and is_round_one
        is_semifinals = is_round_two if (number_of_playoff_teams > 4) else is_round_one
        is_finals = is_round_three if (number_of_playoff_teams > 4) else is_round_two
        is_consolation_finals = is_semifinals if (number_of_teams_in_league < 12 and number_of_playoff_teams > 4) else is_finals
        is_consolation_over = is_round_three and not is_consolation_finals

        for s in box_scores:
            if not hasattr(s.home_team, 'owner') or not hasattr(s.away_team, 'owner'):
                continue

            if s.matchup_type == 'WINNERS_CONSOLATION_LADDER':
                continue

            winner = player_lookup_by_espn_name[s.home_team.owner]['player_id']
            loser = player_lookup_by_espn_name[s.away_team.owner]['player_id']
            winning_score = s.home_score
            losing_score = s.away_score
            winning_team = s.home_team
            losing_team = s.away_team
            if (s.away_score > s.home_score):
                winner = player_lookup_by_espn_name[s.away_team.owner]['player_id']
                loser = player_lookup_by_espn_name[s.home_team.owner]['player_id']
                winning_score = s.away_score
                losing_score = s.home_score
                winning_team = s.away_team
                losing_team = s.home_team

            if s.matchup_type == 'LOSERS_CONSOLATION_LADDER':
                if is_consolation_over:
                   continue

                # HACK - if they won any completed consolation game, ignore the box score
                index_for_round_two = last_week_of_regular_season + 2 - 1
                if is_round_three:
                    round_two_winners_game = winning_team.outcomes[index_for_round_two]
                    round_two_losers_game = losing_team.outcomes[index_for_round_two]
                    if round_two_winners_game == 'W' or round_two_losers_game == 'W':
                        continue

                index_for_round_one = last_week_of_regular_season + 1 - 1
                if not is_round_one:
                    round_one_winners_game = winning_team.outcomes[index_for_round_one]
                    round_one_losers_game = losing_team.outcomes[index_for_round_one]
                    if round_one_winners_game == 'W' or round_one_losers_game == 'W':
                        continue

            home_name = player_lookup_by_espn_name[s.home_team.owner]['display_name']
            matchup_string = home_name + ' - ' + str(s.home_score)
            if (s.home_projected != -1 and not math.isclose(s.home_score, s.home_projected, abs_tol=0.01)):
                matchup_string += ' (' + str(s.home_projected) + ')'

            away_name = player_lookup_by_espn_name[s.away_team.owner]['display_name']
            matchup_string += ' versus ' + away_name + ' - ' + str(s.away_score)
            if (s.away_projected != -1 and not math.isclose(s.away_score, s.away_projected, abs_tol=0.01)):
                matchup_string += ' (' + str(s.away_projected) + ')'

            message['attachments'].append({ 'text': matchup_string })

            score_result = {
                'winner': winner,
                'loser': loser,
                'winning_score': winning_score,
                'losing_score': losing_score
            }

            if s.is_playoff:
                score_result['winning_seed'] = winning_team.standing
                score_result['losing_seed'] = losing_team.standing
                score_result['consolation'] = s.matchup_type == 'LOSERS_CONSOLATION_LADDER'

            if is_consolation_finals and score_result['consolation']:
                score_result['championship'] = True
                score_result['third_place'] = False

            if is_finals and not score_result['consolation']:
                #if s.matchup_type == 'WINNERS_CONSOLATION_LADDER':
                if s.matchup_type == 'THIRD_PLACE_GAME':
                    score_result['championship'] = False
                    score_result['third_place'] = True
                else:
                    score_result['championship'] = True
                    score_result['third_place'] = False

            matchups.append(score_result)

        # TODO - there's a mix of string and int types stored for years and weeks, pick one (probably int)
        database_key = { 'year': int(LEAGUE_YEAR), 'week': week }
        mongo.db.scores.update_one(database_key, {
            '$set': {
                'year': int(LEAGUE_YEAR),
                'week': week,
                'matchups': matchups,
                'playoffs': is_playoff,
                'quarterfinals': is_quarterfinals,
                'semifinals': is_semifinals,
                'finals': is_finals,
            },
        # insert if you need to, and make sure to guarantee one record per year/week
        }, upsert=True)

        #app.logger.debug("metadata")
        return message
    def get(self):
        return Scoreboard.post(self)

@api.route('/scoreboard/matchupresults/')
class MatchupResults(restful.Resource):
    def post(self):
        # previously, this only ran when the server started; now we can make sure week metadata is up to date here
        refresh_week_constants()

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
        mongo.db.matchup_results.update_one(database_key, {
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
        }, upsert=True)

        results_string = 'Matchup calculations for week ' + LAST_LEAGUE_WEEK + ' of ' + LEAGUE_YEAR + ':\n'
        results_string += 'Winners: ' + ', '.join(winners) + '\n'
        results_string += 'Blowout: ' + blowout_matchup
        results_string += ' | Closest: ' + closest_matchup + '\n'
        results_string += 'Highest: ' + highest_scorer + ', ' + str(high_score) + ' | '
        results_string += 'Lowest: ' + lowest_scorer + ', ' + str(low_score)

        return Response(results_string)
    def get(self):
        return MatchupResults.post(self)

@api.route('/scoreboard/tiebreakers/')
class Tiebreakers(restful.Resource):
    def post(self):
        message = {
            'response_type': 'in_channel',
            'text': 'Tiebreaker calculations for week ' + LEAGUE_WEEK + ' (waivers by fewest wins/points, draft standings by most):',
            'attachments': []
        }

        # can't calculate tiebreakers for the week before in the first week
        # in practice, __init__.py checks for the latest week to start
        if LEAGUE_WEEK == '1':
            return Response('Tiebreaker calculations are not available until the morning (8am) after Monday Night Football.')

        # TODO - there's a mix of string and int types stored for years and weeks, pick one (probably int)
        week = int(LAST_LEAGUE_WEEK)
        week_before = week - 1
        previous_standings = mongo.db.prediction_standings.find({ 'year': LEAGUE_YEAR, 'week': str(week_before) }) if week_before > 0 else []
        # TODO - return error if no prediction standings are found
        current_standings = mongo.db.prediction_standings.find({ 'year': LEAGUE_YEAR, 'week': LAST_LEAGUE_WEEK })
        # TODO - prefetch player_metadata in __init__.py (like MATCHUPS)
        player_lookup_by_username = {}
        for p in mongo.db.player_metadata.find():
            player_lookup_by_username[p['slack_username']] = p

        league = League(league_id=int(LEAGUE_ID), year=int(LEAGUE_YEAR), espn_s2=ESPN_S2, swid=ESPN_SWID)

        last_week_of_regular_season = league.settings.reg_season_count
        number_of_playoff_teams = league.settings.playoff_team_count

        is_playoff = week > last_week_of_regular_season
        is_round_two = last_week_of_regular_season + 2 == week
        is_round_three = last_week_of_regular_season + 3 == week
        is_finals = is_round_three if (number_of_playoff_teams > 4) else is_round_two

        team_lookup_by_espn_name = {}
        for t in league.teams:
            team_lookup_by_espn_name[t.owner] = t

        previous_standings_lookup_by_username = {}
        if week_before > 0:
            for ps in previous_standings:
                previous_standings_lookup_by_username[ps['username']] = ps

        season_standings_to_sort = []
        week_standings_to_sort = []
        for team in current_standings:
            total = team['total'] or 0
            username = team['username']
            espn_owner_name = player_lookup_by_username[username]['espn_owner_name']
            espn_team = team_lookup_by_espn_name[espn_owner_name]
            team_wins = espn_team.wins
            team_points = espn_team.points_for

            # ESPN doesn't factor in playoff wins/points, so we have to add those ourselves
            if is_playoff:
                if last_week_of_regular_season + 1 <= week:
                    index = last_week_of_regular_season
                    outcome = espn_team.outcomes[index]
                    # (bye weeks count as wins, and bye week points count)
                    if (outcome == 'W' or outcome == 'U'):
                        team_wins += 1
                    team_points += espn_team.scores[index]
                if last_week_of_regular_season + 2 <= week:
                    index = last_week_of_regular_season + 1
                    outcome = espn_team.outcomes[index]
                    if (outcome == 'W' or outcome == 'U'):
                        team_wins += 1
                    team_points += espn_team.scores[index]
                if last_week_of_regular_season + 3 <= week:
                    index = last_week_of_regular_season + 2
                    outcome = espn_team.outcomes[index]
                    if (outcome == 'W' or outcome == 'U'):
                        team_wins += 1
                    team_points += espn_team.scores[index]

            season_standings_to_sort.append({
                    'username': username,
                    'total': total,
                    'final_standing': espn_team.final_standing
                })

            if week_before > 0:
                week_total = total - previous_standings_lookup_by_username[username]['total']
                week_standings_to_sort.append({
                        'username': username,
                        'total': week_total,
                        'wins': team_wins,
                        'points': Decimal(team_points),
                        'random': random.randint(0, 100)
                    })

        if week_before == 0:
            week_standings_grouped_by_total = copy.deepcopy(season_standings_grouped_by_total)

        if not is_finals:
            week_string = 'Week ' + LEAGUE_WEEK + ' Waiver Order:\n'

            # break ties by least wins, then least points, then coin flip
            for team in sorted(week_standings_to_sort, key=lambda t: (-t['total'], t['wins'], t['points'], t['random'])):
                week_string += str(team['total']) + ' - ' + team['username']
                if sum(t['total'] == team['total'] for t in week_standings_to_sort) > 1:
                    week_string += ' (' + str(team['wins']) + ' wins'

                    if sum((t['total'], t['wins']) == (team['total'], team['wins']) for t in week_standings_to_sort) > 1:
                        week_string += ', ' + str(round(team['points'], 2)) + ' points'

                    week_string += ')'

                    number_of_remaining_teams = sum((t['total'], t['wins'], t['points']) == (team['total'], team['wins'], team['points']) for t in week_standings_to_sort)
                    if number_of_remaining_teams > 1:
                        week_string += '\n' + '***COIN FLIP TIEBREAKER APPLIED WITH RANDOM NUMBER***'
                week_string += '\n'

            message['attachments'].append({ 'text': week_string })

        season_string = 'Final ' if is_finals else ''
        season_string += 'Draft Selection Standings for ' + LEAGUE_YEAR + ':\n'

        for team in sorted(season_standings_to_sort, key=lambda t: (-t['total'], t['final_standing'])):
            season_string += str(team['total']) + ' - ' + team['username']
            if sum(t['total'] == team['total'] for t in season_standings_to_sort) > 1:
                if team['final_standing']:
                    rank = team['final_standing']
                    ordinal_suffix = ['th', 'st', 'nd', 'rd', 'th'][min(rank % 10, 4)]
                    season_string += '(finished ' + str(rank) + ordinal_suffix + ')'
            season_string += '\n'

        message['attachments'].append({ 'text': season_string })
        return message
    def get(self):
        return Tiebreakers.post(self)

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
            manager_one_reg_season_list = list(manager_one_reg_season_query)
            manager_one_reg_season_wins = len(manager_one_reg_season_list)
            manager_one_playoff_query = mongo.db.scores.find({ '$and': [
                { 'matchups':
                    { '$elemMatch': {
                        'winner': manager_one_id,
                        'loser': manager_two_id,
                        'consolation': { '$in': [ None, False ] }
                    } }
                }, { 'playoffs': True } ] })
            manager_one_playoff_list = list(manager_one_playoff_query)
            manager_one_playoff_wins = len(manager_one_playoff_list)
            manager_one_consolation_query = mongo.db.scores.find({ '$and': [
                { 'matchups':
                    { '$elemMatch': {
                        'winner': manager_one_id,
                        'loser': manager_two_id,
                        'consolation': True
                    } }
                }, { 'playoffs': True } ] })
            manager_one_consolation_list = list(manager_one_consolation_query)
            manager_one_consolation_wins = len(manager_one_consolation_list)

            manager_two_reg_season_query = mongo.db.scores.find({ '$and': [
                { 'matchups':
                    { '$elemMatch': {
                        'winner': manager_two_id,
                        'loser': manager_one_id
                    } }
                }, { 'playoffs': False } ] })
            manager_two_reg_season_list = list(manager_two_reg_season_query)
            manager_two_reg_season_wins = len(manager_two_reg_season_list)
            manager_two_playoff_query = mongo.db.scores.find({ '$and': [
                { 'matchups':
                    { '$elemMatch': {
                        'winner': manager_two_id,
                        'loser': manager_one_id,
                        'consolation': { '$in': [ None, False ] }
                    } }
                }, { 'playoffs': True } ] })
            manager_two_playoff_list = list(manager_two_playoff_query)
            manager_two_playoff_wins = len(manager_two_playoff_list)
            manager_two_consolation_query = mongo.db.scores.find({ '$and': [
                { 'matchups':
                    { '$elemMatch': {
                        'winner': manager_two_id,
                        'loser': manager_one_id,
                        'consolation': True
                    } }
                }, { 'playoffs': True } ] })
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
                playoff_years_list = manager_one_playoff_list + manager_two_playoff_list
                matchup_string += ' (' + ', '.join(build_playoff_history_string(e, manager_ids) for e in playoff_years_list) + ')'

            if (manager_one_consolation_wins + manager_two_consolation_wins) > 0:
                # keep same order as regular season record
                if manager_one_reg_season_wins > manager_two_reg_season_wins:
                    matchup_string += '\n- ' + str(manager_one_consolation_wins) + '-' + str(manager_two_consolation_wins) + ' in consolation'
                else:
                    matchup_string += '\n- ' + str(manager_two_consolation_wins) + '-' + str(manager_one_consolation_wins) + ' in consolation'
                consolation_years_list = manager_one_consolation_list + manager_two_consolation_list
                matchup_string += ' (' + ', '.join(build_consolation_history_string(e) for e in consolation_years_list) + ')'

            # one message attachment per matchup
            message['attachments'].append({ 'text': matchup_string })

        return message
    def get(self):
        return HeadToHeadHistory.post(self)

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
