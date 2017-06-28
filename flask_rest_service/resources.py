import json
from flask import request, abort
from flask.ext import restful
from flask.ext.restful import reqparse
from flask_rest_service import app, api, mongo
from bson.objectid import ObjectId
import requests

class Root(restful.Resource):
    def get(self):
        webhook_url = 'https://hooks.slack.com/services/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'
        headers = { 'content-type': 'application/json' }
        payload = json.dumps({
            'text': 'I have integrated this proof of concept, from an API server on Heroku to the webhook that posted this message. This took way longer than it fucking should have.'
        })
        request = requests.post(webhook_url, headers=headers, data=payload)

        return {
            'status': 'OK',
            'mongo': str(mongo.db),
        }

api.add_resource(Root, '/')
