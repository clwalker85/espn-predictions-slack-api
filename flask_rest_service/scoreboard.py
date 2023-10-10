import copy
import os
import json
import math
import pprint
import random
import requests
from decimal import Decimal
from datetime import datetime, time, timedelta
from flask import request, abort, Response
import flask_restful as restful
# see __init__.py for these definitions
from flask_rest_service import app, api, mongo, metadata, post_to_slack, open_dialog, update_message

@api.route('/scoreboard/')
class Scoreboard(restful.Resource):
    def post(self):
        # for direct Slack commands, you don't get a payload like an interactive message action,
        # you have to parse the text of the parameters
        #text = request.form.get('text', None)
        #param = text.split()
        #query_type = param[0]

        #if query_type == 'help':
        #message['attachments'].append({ 'text': some_help_output_string })

        message = {
            'response_type': 'in_channel',
            'text': '',
            'attachments': []
        }

        # show last week until projections are due and week hasn't officially ended
        week_shown = metadata.last_league_week
        if datetime.now() > metadata.deadline_time:
            week_shown = metadata.league_week

        matchups = []
        week = int(week_shown)
        box_scores = metadata.espn.box_scores(week)

        last_week_of_regular_season = metadata.espn.weeks_in_regular_season
        number_of_teams_in_league = metadata.espn.number_of_teams
        number_of_playoff_teams = metadata.espn.number_of_playoff_teams

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

            winner = metadata.player_lookup_by_espn_name[s.home_team.owner]['player_id']
            loser = metadata.player_lookup_by_espn_name[s.away_team.owner]['player_id']
            winning_score = s.home_score
            losing_score = s.away_score
            winning_team = s.home_team
            losing_team = s.away_team
            if (s.away_score > s.home_score):
                winner = metadata.player_lookup_by_espn_name[s.away_team.owner]['player_id']
                loser = metadata.player_lookup_by_espn_name[s.home_team.owner]['player_id']
                winning_score = s.away_score
                losing_score = s.home_score
                winning_team = s.away_team
                losing_team = s.home_team

            if s.matchup_type == 'WINNERS_CONSOLATION_LADDER':
                if is_round_three:
                    index_for_round_two = last_week_of_regular_season + 2 - 1
                    round_two_winners_game = winning_team.outcomes[index_for_round_two]
                    round_two_losers_game = losing_team.outcomes[index_for_round_two]
                    # if either team won the last game, this isn't the third place game
                    if round_two_winners_game == 'W' or round_two_losers_game == 'W':
                        continue
                else:
                    continue

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

            home_name = metadata.player_lookup_by_espn_name[s.home_team.owner]['display_name']
            matchup_string = home_name + ' - ' + str(s.home_score)
            if (s.home_projected != -1 and not math.isclose(s.home_score, s.home_projected, abs_tol=0.01)):
                matchup_string += ' (' + str(s.home_projected) + ')'

            away_name = metadata.player_lookup_by_espn_name[s.away_team.owner]['display_name']
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
                if s.matchup_type == 'WINNERS_CONSOLATION_LADDER':
                    score_result['championship'] = False
                    score_result['third_place'] = True
                else:
                    score_result['championship'] = True
                    score_result['third_place'] = False

            matchups.append(score_result)

        # TODO - there's a mix of string and int types stored for years and weeks, pick one (probably int)
        database_key = { 'year': int(metadata.league_year), 'week': week }
        # guarantee one record per year/week
        mongo.db.scores.update_one(database_key, {
            '$set': {
                'year': int(metadata.league_year),
                'week': week,
                'matchups': matchups,
                'playoffs': is_playoff,
                'quarterfinals': is_quarterfinals,
                'semifinals': is_semifinals,
                'finals': is_finals,
            },
        }, upsert=True)

        return message
    def get(self):
        return Scoreboard.post(self)

@api.route('/scoreboard/matchupresults/')
class MatchupResults(restful.Resource):
    def post(self):
        # can't calculate matchup results for the week before in the first week
        # in practice, __init__.py checks for the latest week to start
        if metadata.league_week == '1':
            return Response('Matchup result calculations are not available until the morning (8am) after Monday Night Football.')

        # TODO - return error if no scores are found
        # TODO - there's a mix of string and int types stored for years and weeks, pick one (probably int)
        scores_result = mongo.db.scores.find_one({ 'year': int(metadata.league_year), 'week': int(metadata.last_league_week) })

        winners = []
        blowout_matchup_winner, blowout_matchup = '', ''
        closest_matchup_winner, closest_matchup = '', ''
        biggest_margin, smallest_margin = 0, 9999
        highest_scorer, lowest_scorer = '', ''
        high_score, low_score = 0, 9999

        for matchup in scores_result['matchups']:
            margin = matchup['winning_score'] - matchup['losing_score']
            winner_name = metadata.player_lookup_by_id[matchup['winner']]['display_name']
            loser_name = metadata.player_lookup_by_id[matchup['loser']]['display_name']

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
                blowout_matchup = winner_name + " versus " + loser_name

            if margin < smallest_margin:
                smallest_margin = margin
                closest_matchup_winner = winner_name
                closest_matchup = winner_name + " versus " + loser_name

        # TODO - there's a mix of string and int types stored for years and weeks, pick one (probably int)
        database_key = { 'year': metadata.league_year, 'week': metadata.last_league_week }
        # guarantee one record per year/week
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
                'year': metadata.league_year,
                'week': metadata.last_league_week
            },
        }, upsert=True)

        results_string = 'Matchup calculations for week ' + metadata.last_league_week + ' of ' + metadata.league_year + ':\n'
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
            'text': 'Tiebreaker calculations for week ' + metadata.league_week + ' (waivers by fewest wins/points, draft standings by most):',
            'attachments': []
        }

        # can't calculate tiebreakers for the week before in the first week
        # in practice, __init__.py checks for the latest week to start
        if metadata.league_week == '1':
            return Response('Tiebreaker calculations are not available until the morning (8am) after Monday Night Football.')

        # TODO - there's a mix of string and int types stored for years and weeks, pick one (probably int)
        week = int(metadata.last_league_week)
        week_before = week - 1
        previous_standings = mongo.db.prediction_standings.find({ 'year': metadata.league_year, 'week': str(week_before) }) if week_before > 0 else []
        # TODO - return error if no prediction standings are found
        current_standings = mongo.db.prediction_standings.find({ 'year': metadata.league_year, 'week': metadata.last_league_week })

        last_week_of_regular_season = metadata.espn.weeks_in_regular_season
        number_of_playoff_teams = metadata.espn.number_of_playoff_teams

        is_playoff = week > last_week_of_regular_season
        is_round_two = last_week_of_regular_season + 2 == week
        is_round_three = last_week_of_regular_season + 3 == week
        is_finals = is_round_three if (number_of_playoff_teams > 4) else is_round_two

        previous_standings_lookup_by_username = {}
        if week_before > 0:
            for ps in previous_standings:
                previous_standings_lookup_by_username[ps['username']] = ps

        season_standings_to_sort = []
        week_standings_to_sort = []
        for team in current_standings:
            total = team['total'] or 0
            username = team['username']
            espn_owner_name = metadata.player_lookup_by_username[username]['espn_owner_name']
            espn_team = metadata.team_lookup_by_espn_name[espn_owner_name]
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

        if is_finals:
            season_string = 'Final Draft Selection Standings for ' + metadata.league_year + ':\n'

            for team in sorted(season_standings_to_sort, key=lambda t: (-t['total'], t['final_standing'])):
                season_string += str(team['total']) + ' - ' + team['username']
                if sum(t['total'] == team['total'] for t in season_standings_to_sort) > 1:
                    if team['final_standing']:
                        rank = team['final_standing']
                        ordinal_suffix = ['th', 'st', 'nd', 'rd', 'th'][min(rank % 10, 4)]
                        season_string += ' (finished ' + str(rank) + ordinal_suffix + ')'
                season_string += '\n'

            message['attachments'].append({ 'text': season_string })
        else:
            week_string = 'Week ' + metadata.league_week + ' Waiver Order:\n'

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

        return message
    def get(self):
        return Tiebreakers.post(self)

@api.route('/scoreboard/schedule')
class Schedule(restful.Resource):
    def post(self):
        if str(datetime.today().year) != metadata.league_year:
            return Response("League metadata must be set before setting this year's schedule; see admin.")

        week_param = request.form.get('text', None)
        if week_param:
            week_param = week_param.strip()

        # if anyone has submitted a prediction for the week, that means we've set the schedule already;
        # block any schedule overwrites (if it's really necessary, it'll require a programmer to circumvent)
        if list(mongo.db.predictions.find({ 'year': metadata.league_year, 'week': week_param })):
            return Response('Matchup schedules cannot be set after a prediction has been submitted this week.')

        if week_param:
            metadata.insert_matchup_data(int(week_param))
            return Response('Week ' + week_param + ' schedule submitted successfully.')

        metadata.insert_matchup_data()
        return Response("Next week's schedule submitted successfully.")

    def get(self):
        return Schedule.post(self)

