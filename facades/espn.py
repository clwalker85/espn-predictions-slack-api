from functools import cached_property
from espn_api.football import League

import os
ESPN_SWID = os.environ.get('ESPN_SWID')
ESPN_S2 = os.environ.get('ESPN_S2')

class Espn:
    def __init__(self, league_id, league_year):
        self.league_id = league_id
        self.league_year = league_year

    @cached_property
    def league(self):
        return League(league_id=int(self.league_id), year=int(self.league_year), espn_s2=ESPN_S2, swid=ESPN_SWID)

    @cached_property
    def teams(self):
        return self.league.teams

    @cached_property
    def settings(self):
        return self.league.settings

    @property
    def weeks_in_regular_season(self):
        return self.settings.reg_season_count

    @property
    def number_of_teams(self):
        return self.settings.team_count

    @property
    def number_of_playoff_teams(self):
        return self.settings.playoff_team_count

    def invalidate_cached_year(self):
        if "league" in self.__dict__:
            del self.__dict__["league"]
        if "teams" in self.__dict__:
            del self.__dict__["teams"]
        if "settings" in self.__dict__:
            del self.__dict__["settings"]

    def box_scores(self, week):
        return self.league.box_scores(week)
