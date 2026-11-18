"""
WSGI configuration for PythonAnywhere
=====================================================
This file is used to load the Django application on PythonAnywhere.
PythonAnywhere will execute this file to start the web application.
"""

import os
import sys
from pathlib import Path

project_dir = Path(__file__).resolve().parent.parent

if str(project_dir) not in sys.path:
    sys.path.insert(0, str(project_dir))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', os.environ.get('DJANGO_SETTINGS_MODULE', 'sdi_market.settings'))

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
