import json
from flask import request, abort
from flask.ext import restful
from flask.ext.restful import reqparse
from flask_rest_service import app, api, mongo
from bson.objectid import ObjectId
import requests
from espnff import League

LEAGUE_ID = 367562
WEBHOOK_URL = 'https://hooks.slack.com/services/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'

def post_to_slack(payload):
    headers = { 'content-type': 'application/json' }
    payload = json.dumps(payload)
    return requests.post(WEBHOOK_URL, headers=headers, data=payload)

def post_text_to_slack(text):
    return post_to_slack({'text': text})

class Root(restful.Resource):
    def get(self):
        #league = League(LEAGUE_ID, 2016),
        return {
            'status': 'OK',
            'mongo': str(mongo.db),
            #'league': league,
            #'scoreboard': league.scoreboard(week=1)
        }

class Scoreboard(restful.Resource):
    def post(self):
        args = self.parser.parse_args()
        year = 2017

        if args['year']:
            year = args['year']

        if args['week']:
            week = args['week']

        league = League(LEAGUE_ID, year)

        post_text_to_slack(league.scoreboard(week=week))

class SendPredictionForm(restful.Resource):
    def post(self):
        post_to_slack({
            'text': 'Make your predictions for this week''s matchups below:',
            'attachments': [
                {
                    'text': 'Freddy versus Joel',
                    'attachment_type': 'default',
                    'actions': [
                        {
                            'name': 'g1winner',
                            'text': 'Freddy',
                            'type': 'button',
                            'value': 'Freddy'
                        },
                        {
                            'name': 'g1winner',
                            'text': 'Joel',
                            'type': 'button',
                            'value': 'Joel'
                        },
                    ]
                },
                {
                    'text': 'Tom versus Alexis',
                    'attachment_type': 'default',
                    'actions': [
                        {
                            'name': 'g2winner',
                            'text': 'Tom',
                            'type': 'button',
                            'value': 'Tom'
                        },
                        {
                            'name': 'g2winner',
                            'text': 'Alexis',
                            'type': 'button',
                            'value': 'Alexis'
                        },
                    ]
                },
                {
                    'text': 'Kevin versus Stan',
                    'attachment_type': 'default',
                    'actions': [
                        {
                            'name': 'g3winner',
                            'text': 'Kevin',
                            'type': 'button',
                            'value': 'Kevin'
                        },
                        {
                            'name': 'g3winner',
                            'text': 'Stan',
                            'type': 'button',
                            'value': 'Stan'
                        },
                    ]
                },
                {
                    'text': 'Todd versus James',
                    'attachment_type': 'default',
                    'actions': [
                        {
                            'name': 'g4winner',
                            'text': 'Todd',
                            'type': 'button',
                            'value': 'Todd'
                        },
                        {
                            'name': 'g4winner',
                            'text': 'James',
                            'type': 'button',
                            'value': 'James'
                        },
                    ]
                },
                {
                    'text': 'Justin versus Mike',
                    'attachment_type': 'default',
                    'actions': [
                        {
                            'name': 'g5winner',
                            'text': 'Justin',
                            'type': 'button',
                            'value': 'Justin'
                        },
                        {
                            'name': 'g5winner',
                            'text': 'Mike',
                            'type': 'button',
                            'value': 'Mike'
                        },
                    ]
                },
                {
                    'text': 'Renato versus Bryant',
                    'attachment_type': 'default',
                    'actions': [
                        {
                            'name': 'g6winner',
                            'text': 'Renato',
                            'type': 'button',
                            'value': 'Renato'
                        },
                        {
                            'name': 'g6winner',
                            'text': 'Bryant',
                            'type': 'button',
                            'value': 'Bryant'
                        },
                    ]
                },
                {
                    'text': 'Walker versus Cathy',
                    'attachment_type': 'default',
                    'actions': [
                        {
                            'name': 'g7winner',
                            'text': 'Walker',
                            'type': 'button',
                            'value': 'Walker'
                        },
                        {
                            'name': 'g7winner',
                            'text': 'Cathy',
                            'type': 'button',
                            'value': 'Cathy'
                        },
                    ]
                },
                {
                    'text': 'Which matchup will have the biggest blowout?',
                    'attachment_type': 'default',
                    'actions': [
                        {
                            'name': 'blowout',
                            'text': 'Pick a matchup...',
                            'type': 'select',
                            'options': [
                                {
                                    'text': 'Freddy versus Joel',
                                    'value': 'Freddy versus Joel'
                                },
                                {
                                    'text': 'Tom versus Alexis',
                                    'value': 'Tom versus Alexis'
                                },
                                {
                                    'text': 'Kevin versus Stan',
                                    'value': 'Kevin versus Stan'
                                },
                                {
                                    'text': 'Todd versus James',
                                    'value': 'Todd versus James'
                                },
                                {
                                    'text': 'Justin versus Mike',
                                    'value': 'Justin versus Mike'
                                },
                                {
                                    'text': 'Renato versus Bryant',
                                    'value': 'Renato versus Bryant'
                                },
                                {
                                    'text': 'Walker versus Cathy',
                                    'value': 'Walker versus Cathy'
                                }
                            ]
                        }
                    ]
                },
                {
                    'text': 'Which matchup will have the closest score?',
                    'attachment_type': 'default',
                    'actions': [
                        {
                            'name': 'closest',
                            'text': 'Pick a matchup...',
                            'type': 'select',
                            'options': [
                                {
                                    'text': 'Freddy versus Joel',
                                    'value': 'Freddy versus Joel'
                                },
                                {
                                    'text': 'Tom versus Alexis',
                                    'value': 'Tom versus Alexis'
                                },
                                {
                                    'text': 'Kevin versus Stan',
                                    'value': 'Kevin versus Stan'
                                },
                                {
                                    'text': 'Todd versus James',
                                    'value': 'Todd versus James'
                                },
                                {
                                    'text': 'Justin versus Mike',
                                    'value': 'Justin versus Mike'
                                },
                                {
                                    'text': 'Renato versus Bryant',
                                    'value': 'Renato versus Bryant'
                                },
                                {
                                    'text': 'Walker versus Cathy',
                                    'value': 'Walker versus Cathy'
                                }
                            ]
                        }
                    ]
                },
                {
                    'text': 'Who will be the highest scorer?',
                    'attachment_type': 'default',
                    'actions': [
                        {
                            'name': 'lowest',
                            'text': 'Pick a team...',
                            'type': 'select',
                            'options': [
                                {
                                    'text': 'Freddy',
                                    'value': 'Freddy'
                                },
                                {
                                    'text': 'Joel',
                                    'value': 'Joel'
                                },
                                {
                                    'text': 'Alexis',
                                    'value': 'Alexis'
                                },
                                {
                                    'text': 'Tom',
                                    'value': 'Tom'
                                },
                                {
                                    'text': 'Stan',
                                    'value': 'Stan'
                                },
                                {
                                    'text': 'Kevin',
                                    'value': 'Kevin'
                                },
                                {
                                    'text': 'Todd',
                                    'value': 'Todd'
                                },
                                {
                                    'text': 'James',
                                    'value': 'James'
                                },
                                {
                                    'text': 'Mike',
                                    'value': 'Mike'
                                },
                                {
                                    'text': 'Justin',
                                    'value': 'Justin'
                                },
                                {
                                    'text': 'Bryant',
                                    'value': 'Bryant'
                                },
                                {
                                    'text': 'Renato',
                                    'value': 'Renato'
                                },
                                {
                                    'text': 'Cathy',
                                    'value': 'Cathy'
                                },
                                {
                                    'text': 'Walker',
                                    'value': 'Walker'
                                }
                            ]
                        }
                    ]
                },
                {
                    'text': 'Who will be the lowest scorer?',
                    'attachment_type': 'default',
                    'actions': [
                        {
                            'name': 'lowest',
                            'text': 'Pick a team...',
                            'type': 'select',
                            'options': [
                                {
                                    'text': 'Freddy',
                                    'value': 'Freddy'
                                },
                                {
                                    'text': 'Joel',
                                    'value': 'Joel'
                                },
                                {
                                    'text': 'Alexis',
                                    'value': 'Alexis'
                                },
                                {
                                    'text': 'Tom',
                                    'value': 'Tom'
                                },
                                {
                                    'text': 'Stan',
                                    'value': 'Stan'
                                },
                                {
                                    'text': 'Kevin',
                                    'value': 'Kevin'
                                },
                                {
                                    'text': 'Todd',
                                    'value': 'Todd'
                                },
                                {
                                    'text': 'James',
                                    'value': 'James'
                                },
                                {
                                    'text': 'Mike',
                                    'value': 'Mike'
                                },
                                {
                                    'text': 'Justin',
                                    'value': 'Justin'
                                },
                                {
                                    'text': 'Bryant',
                                    'value': 'Bryant'
                                },
                                {
                                    'text': 'Renato',
                                    'value': 'Renato'
                                },
                                {
                                    'text': 'Cathy',
                                    'value': 'Cathy'
                                },
                                {
                                    'text': 'Walker',
                                    'value': 'Walker'
                                }
                            ]
                        }
                    ]
                }
            ]
        })

api.add_resource(Root, '/')
api.add_resource(Scoreboard, '/scoreboard/')
api.add_resource(SendPredictionForm, '/prediction/form/')
