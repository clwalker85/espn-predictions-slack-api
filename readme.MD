# Install
```
virtualenv venv
source venv/bin/activate
pip install -r requirements.txt
```

# Running
This will run under gunicorn or standalone.

`python runserver.py`
or
`gunicorn --bind 0.0.0.0:5000 wsgi:app`

# Documentation

If you want to contribute, start here to read how Slack prediction forms work with our fantasy football league:

https://github.com/clwalker85/espn-predictions-slack-api/blob/main/flask_rest_service/predictions.py
