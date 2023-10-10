from functools import cached_property
from datetime import datetime, time, timedelta
from espn_api.football import League

import os
ESPN_SWID = os.environ.get('ESPN_SWID')
ESPN_S2 = os.environ.get('ESPN_S2')

class Metadata:
    def __init__(self, app, mongo):
        self.app = app
        self.mongo = mongo

    @cached_property
    def league(self):
        # TODO - Find a way to fetch some of this through the ESPN API when teams are locked in
        # Might have to always manually link an ESPN user to their Slack user
        with self.app.app_context():
            return self.mongo.db.league_metadata.find_one(sort=[('year', -1)])

    @property
    def league_id(self):
        return self.league['league_id']

    @property
    def league_year(self):
        return self.league['year']

    @property
    def members(self):
        return [m['display_name'] for m in self.league['members']]

    @property
    def usernames(self):
        return [m['slack_username'] for m in self.league['members']]

    @property
    def user_ids(self):
        return [m['slack_user_id'] for m in self.league['members']]

    # get the matchup data for the current week
    # IF IT DOESN'T EXIST FOR THIS WEEK, THIS API WILL COME TO A CRASHING HALT
    @cached_property
    def matchup_data(self):
        with self.app.app_context():
            matchup = self.mongo.db.matchup_metadata.find_one({ 'year': self.league_year,
                'start_of_week_time': { '$lte': datetime.now() } }, sort=[('start_of_week_time', -1)])
            # if no matchup data exists for the year, create the first week
            if not matchup:
                return self.insert_matchup_data(1)
            return matchup

    @property
    def league_week(self):
        return self.matchup_data['week']

    @property
    def tz_aware_deadline_time(self):
        return self.matchup_data['deadline_time']

    @property
    def deadline_time(self):
        return self.tz_aware_deadline_time.replace(tzinfo=None)

    @property
    def deadline_string(self):
        # strftime doesn't provide anything besides zero-padded numbers in formats,
        # so it looks like -------------------------------------> "December 23, 2017, at 04:30PM"
        # TODO - Use a better date formatter, to try and get ---> "December 23rd, 2017, at 4:30PM"
        return self.deadline_time.strftime('%B %d, %Y, at %I:%M%p ')

    @property
    def matchups(self):
        return self.matchup_data['matchups']

    @property
    def prediction_eligible_members(self):
        return [m['team_one'] for m in self.matchups] + [m['team_two'] for m in self.matchups]

    @cached_property
    def last_matchup_data(self):
        with self.app.app_context():
            last_matchup = self.mongo.db.matchup_metadata.find_one({ 'year': self.league_year,
                'end_of_week_time': { '$lte': datetime.now() } }, sort=[('end_of_week_time', -1)])
            if not last_matchup:
                return self.matchup_data
            return last_matchup

    @property
    def last_league_week(self):
        return self.last_matchup_data['week']

    def invalidate_cached_year(self):
        if "league" in self.__dict__:
            del self.__dict__["league"]
        if "matchup_data" in self.__dict__:
            del self.__dict__["matchup_data"]
        if "last_matchup_data" in self.__dict__:
            del self.__dict__["last_matchup_data"]

    def invalidate_cached_week(self):
        if "matchup_data" in self.__dict__:
            del self.__dict__["matchup_data"]
        if "last_matchup_data" in self.__dict__:
            del self.__dict__["last_matchup_data"]

    def insert_matchup_data(self, week=None):
        week_string = str(week)
        if not week:
            week_string = str(int(self.league_week) + 1)

        next_tuesday_candidate = datetime.today()
        if week_string != '1' and self.last_matchup_data:
            next_tuesday_candidate = self.last_matchup_data['end_of_week_time']
        # `1` represents Tuesday
        elif next_tuesday_candidate.weekday() == 1:
            next_tuesday_candidate += timedelta(days=7)
        else:
            while next_tuesday_candidate.weekday() != 1:
                next_tuesday_candidate += timedelta(days=1)

        eight_am = time(hour=8)
        start_of_week_time = datetime.combine(next_tuesday_candidate, eight_am)
        end_of_week_time = datetime.combine(start_of_week_time + timedelta(days=7), eight_am)

        eight_fifteen_pm = time(hour=20, minute=15)
        deadline_time = datetime.combine(start_of_week_time + timedelta(days=2), eight_fifteen_pm)
        # Thanksgiving is fourth Thursday in November and uses a different deadline time
        if deadline_time.month == 10 and deadline_time.day // 7 > 3:
            twelve_thirty_pm = time(hour=12, minute=30)
            deadline_time = datetime.combine(deadline_time, twelve_thirty_pm)

        # TODO - make player_metadata a cached_property
        player_lookup_by_espn_name = {}
        for p in self.mongo.db.player_metadata.find():
            if p['espn_owner_name']:
                player_lookup_by_espn_name[p['espn_owner_name']] = p

        matchups = []
        league = League(league_id=int(self.league_id), year=int(self.league_year), espn_s2=ESPN_S2, swid=ESPN_SWID)
        week = int(week_string)
        box_scores = league.box_scores(week)

        last_week_of_regular_season = league.settings.reg_season_count
        number_of_teams_in_league = league.settings.team_count
        number_of_playoff_teams = league.settings.playoff_team_count

        is_round_one = last_week_of_regular_season + 1 == week
        is_round_two = last_week_of_regular_season + 2 == week
        is_round_three = last_week_of_regular_season + 3 == week
        is_semifinals = is_round_two if (number_of_playoff_teams > 4) else is_round_one
        is_finals = is_round_three if (number_of_playoff_teams > 4) else is_round_two
        is_consolation_finals = is_semifinals if (number_of_teams_in_league < 12 and number_of_playoff_teams > 4) else is_finals
        is_consolation_over = is_round_three and not is_consolation_finals
        index_for_round_two = last_week_of_regular_season + 2 - 1
        index_for_round_one = last_week_of_regular_season + 1 - 1

        # TODO - save these as ints instead
        database_key = { 'year': self.league_year, 'week': week_string }

        for s in box_scores:
            if not hasattr(s.home_team, 'owner') or not hasattr(s.away_team, 'owner'):
                continue

            if s.matchup_type == 'WINNERS_CONSOLATION_LADDER':
                if is_round_three:
                    # if either team won the last game, this isn't the third place game
                    if round_two_home_game == 'W' or round_two_away_game == 'W':
                        continue
                else:
                    continue

            if s.matchup_type == 'LOSERS_CONSOLATION_LADDER':
                if is_consolation_over:
                   continue

                # HACK - if they won any completed consolation game, ignore the box score
                if is_round_three:
                    round_two_home_game = s.home_team.outcomes[index_for_round_two]
                    round_two_away_game = s.away_team.outcomes[index_for_round_two]

                    if round_two_home_game == 'W' or round_two_away_game == 'W':
                        continue

                if not is_round_one:
                    round_one_home_game = s.home_team.outcomes[index_for_round_one]
                    round_one_away_game = s.away_team.outcomes[index_for_round_one]

                    if round_one_home_game == 'W' or round_one_away_game == 'W':
                        continue

            home_name = player_lookup_by_espn_name[s.home_team.owner]['display_name']
            away_name = player_lookup_by_espn_name[s.away_team.owner]['display_name']

            matchup = {
                'team_one': away_name,
                'team_two': home_name,
                # TODO - insert player IDs as well, for migration away from strings
            }

            matchups.append(matchup)

        record = {
            # TODO - save these as ints instead
            'year': self.league_year,
            'week': week_string,
            'matchups': matchups,
            'start_of_week_time': start_of_week_time,
            'deadline_time': deadline_time,
            'end_of_week_time': end_of_week_time,
        }

        # guarantee one record per year/week
        self.mongo.db.matchup_metadata.update_one(database_key, {
            '$set': record
        }, upsert=True)

        return record
