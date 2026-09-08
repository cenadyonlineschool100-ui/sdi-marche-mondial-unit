#!/usr/bin/env python
"""
Helper script to generate PythonAnywhere configuration
Run this to generate a secure SECRET_KEY and environment variables
"""

from django.core.management.utils import get_random_secret_key
import json

def generate_pythonanywhere_config():
    """Generate secure configuration for PythonAnywhere"""
    
    secret_key = get_random_secret_key()
    
    config = {
        "DJANGO_SECRET_KEY": secret_key,
        "DEBUG": "False",
        "ALLOWED_HOSTS": "YOUR_USERNAME.pythonanywhere.com",
        "DJANGO_SETTINGS_MODULE": "sdi_market.settings",
        "SECURE_SSL_REDIRECT": "False",
        "SESSION_COOKIE_SECURE": "False",
        "CSRF_COOKIE_SECURE": "False",
        "DATABASE_URL": "sqlite:///db.sqlite3",
        "EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend",
    }
    
    print("=" * 60)
    print("PythonAnywhere Configuration")
    print("=" * 60)
    print("\n📋 Copy these environment variables to PythonAnywhere:\n")
    
    for key, value in config.items():
        print(f"{key}={value}")
    
    print("\n" + "=" * 60)
    print("⚠️  Important: Replace 'YOUR_USERNAME' with your actual PythonAnywhere username")
    print("=" * 60)
    
    # Save to file
    with open('pythonanywhere_config.json', 'w') as f:
        json.dump(config, f, indent=2)
    
    print("\n✅ Configuration saved to 'pythonanywhere_config.json'")
    return config

if __name__ == '__main__':
    import os
    import django
    from pathlib import Path
    
    # Setup Django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sdi_market.settings')
    django.setup()
    
    generate_pythonanywhere_config()
