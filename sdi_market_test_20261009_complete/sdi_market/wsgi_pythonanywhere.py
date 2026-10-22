"""
WSGI configuration for PythonAnywhere
=====================================================
This file is used to load the Django application on PythonAnywhere.
PythonAnywhere will execute this file to start the web application.
"""

import os
import sys
from pathlib import Path

# Add the project directory to the Python path
project_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_dir))

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sdi_market.settings')

# Import Django's WSGI application
from django.core.wsgi import get_wsgi_application

# Get the WSGI application
application = get_wsgi_application()
