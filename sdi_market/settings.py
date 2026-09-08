import os
import sys
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent

# Charger les variables d'environnement depuis .env si présent
ENV_PATH = BASE_DIR / '.env'
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if sep and key and value:
            os.environ.setdefault(key.strip(), value.strip().strip('"\''))

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-your-secret-key-change-in-production')

DEBUG = os.getenv('DEBUG', 'False').lower() in ['true', '1', 'yes']

ALLOWED_HOSTS = [host.strip() for host in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,chouchoum.pythonanywhere.com,www.chouchoum.pythonanywhere.com').split(',') if host.strip()]
DEFAULT_CSRF_ORIGINS = 'http://localhost:8000,http://127.0.0.1:8000,https://localhost:8000,https://127.0.0.1:8000,https://chouchoum.pythonanywhere.com,https://www.chouchoum.pythonanywhere.com'
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.getenv('CSRF_TRUSTED_ORIGINS', DEFAULT_CSRF_ORIGINS).split(',') if origin.strip()]
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = not DEBUG
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
# Google Maps API Key - À configurer pour le système de livraison
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', 'VOTRE_CLE_GOOGLE_MAPS_API_ICI')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',
    'marketplace',
    'beauty',
    'rest_framework',
    'rest_framework_simplejwt',
    'channels',
    'savings',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'marketplace.middleware.SystemLockdownMiddleware',
    'marketplace.middleware.SecurityEventMiddleware',
    'marketplace.security_enhanced.AdvancedSecurityMiddleware',  # Sécurité avancée: rate limiting, anomalies
]

ROOT_URLCONF = 'sdi_market.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'builtins': [
                'marketplace.templatetags.marketplace_filters',
            ],
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'marketplace.context_processors.currency_context',
                'marketplace.context_processors.site_config_context',
                'marketplace.context_processors.activity_menu_context',
                'marketplace.context_processors.private_chat_context',
                'marketplace.context_processors.system_settings_context',
                'marketplace.context_processors.announcement_context',
                'marketplace.context_processors.site_banner_context',
                'marketplace.context_processors.navigation_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'sdi_market.wsgi.application'

DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL:
    parsed_db = urlparse(DATABASE_URL)
    if parsed_db.scheme in ['postgres', 'postgresql']:
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.postgresql',
                'NAME': parsed_db.path[1:],
                'USER': parsed_db.username,
                'PASSWORD': parsed_db.password,
                'HOST': parsed_db.hostname,
                'PORT': parsed_db.port or '5432',
            }
        }
    elif parsed_db.scheme in ['mysql']:
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.mysql',
                'NAME': parsed_db.path[1:],
                'USER': parsed_db.username,
                'PASSWORD': parsed_db.password,
                'HOST': parsed_db.hostname,
                'PORT': parsed_db.port or '3306',
            }
        }
    elif parsed_db.scheme in ['sqlite', 'sqlite3']:
        db_path = parsed_db.path.lstrip('/') or 'db.sqlite3'
        DATABASES = {
            'default': {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': BASE_DIR / db_path,
            }
        }
    else:
        raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed_db.scheme}")
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

REDIS_URL = os.getenv('REDIS_URL')
if REDIS_URL:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [REDIS_URL],
            },
        }
    }
else:
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'fr-fr'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

# Configuration des médias (images uploadées)
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / "staticfiles"

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MARKETPLACE_INACTIVITY_TIMEOUT_SECONDS = 600

# Clé API Unsplash pour génération automatique d'images
# À remplacer par une vraie clé API depuis https://unsplash.com/developers
UNSPLASH_ACCESS_KEY = 'YOUR_UNSPLASH_ACCESS_KEY_HERE'

# Google Maps API Key - À configurer pour le système de livraison
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY', 'AIzaSyDUMMY_API_KEY_FOR_DEMO_PURPOSES_ONLY')

# Configuration email
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True').lower() in ['true', '1', 'yes']
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@sdistore.com')

# Configuration Channels pour WebSockets temps réel
ASGI_APPLICATION = 'sdi_market.asgi.application'

# Configuration Redis pour Channels (optionnel, peut utiliser InMemoryChannelLayer)
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer"
    }
}

# Configuration CORS pour les requêtes API
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",  # Pour React/Next.js frontend
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
CORS_ALLOW_CREDENTIALS = True

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', 'True').lower() in ['true', '1', 'yes']
SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'True' if SECURE_SSL_REDIRECT else 'False').lower() in ['true', '1', 'yes']
CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', 'True' if SECURE_SSL_REDIRECT else 'False').lower() in ['true', '1', 'yes']
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '31536000' if SECURE_SSL_REDIRECT else '0'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'True' if SECURE_SSL_REDIRECT else 'False').lower() in ['true', '1', 'yes']
SECURE_HSTS_PRELOAD = os.getenv('SECURE_HSTS_PRELOAD', 'True' if SECURE_SSL_REDIRECT else 'False').lower() in ['true', '1', 'yes']
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'marketplace.User'

# Utiliser le login personnalisé défini dans marketplace.urls
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'loggers': {
        'django.request': {
            'handlers': ['console'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
}

# Django Debug Toolbar - activation en développement uniquement
is_running_tests = any(arg == 'test' or arg.startswith('test') for arg in sys.argv)
if DEBUG and not is_running_tests:
    try:
        INSTALLED_APPS += ['debug_toolbar']
    except NameError:
        INSTALLED_APPS = INSTALLED_APPS + ['debug_toolbar']

    # Placer le middleware de debug toolbar assez tôt
    try:
        MIDDLEWARE.insert(1, 'debug_toolbar.middleware.DebugToolbarMiddleware')
    except Exception:
        # en cas d'erreur de positionnement, append en fin
        MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware']

    INTERNAL_IPS = ['127.0.0.1', 'localhost']
    DEBUG_TOOLBAR_CONFIG = {
        'SHOW_TOOLBAR_CALLBACK': lambda request: True,
    }


