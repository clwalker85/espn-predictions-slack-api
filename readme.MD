# Install
>virtualenv venv
>source venv/bin/activate
>pip install -r requirements.txt

# Running
This will run under gunicorn or standalone.

`python runserver.py`
or
`gunicorn --bind 0.0.0.0:5000 wsgi:app`
