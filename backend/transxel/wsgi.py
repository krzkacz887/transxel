"""Punkt wejścia WSGI (python manage.py runserver / gunicorn transxel.wsgi)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "transxel.settings")
application = get_wsgi_application()
