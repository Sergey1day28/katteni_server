import json
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
LOCAL_SETTINGS_PATH = BASE_DIR / 'farm.local.json'


def load_local_settings(path):
    if not path.exists():
        raise ImproperlyConfigured(
            'Нет farm.local.json. Скопируйте farm.local.example.json, заполните и положите рядом с manage.py.'
        )
    with path.open(encoding='utf-8') as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ImproperlyConfigured('farm.local.json должен быть объектом JSON.')
    return data


LOCAL = load_local_settings(LOCAL_SETTINGS_PATH)

SECRET_KEY = LOCAL.get('secret_key') or ''
if not SECRET_KEY:
    raise ImproperlyConfigured('В farm.local.json пустой secret_key.')

DEBUG = bool(LOCAL.get('debug', False))
ALLOWED_HOSTS = list(LOCAL.get('allowed_hosts') or ['127.0.0.1'])

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'farm_core.apps.FarmCoreConfig',
    'farm_agent_api.apps.FarmAgentApiConfig',
    'farm_api.apps.FarmApiConfig',
    'farm_console.apps.FarmConsoleConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'farm_site.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'farm_site.wsgi.application'

_database = LOCAL.get('database') or {}
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': _database.get('name') or 'katteni_farm',
        'USER': _database.get('user') or '',
        'PASSWORD': _database.get('password') or '',
        'HOST': _database.get('host') or '127.0.0.1',
        'PORT': str(_database.get('port') or '5432'),
        'OPTIONS': {
            'connect_timeout': 5,
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ru-ru'
TIME_ZONE = 'Europe/Moscow'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = '/farm/login/'
LOGIN_REDIRECT_URL = '/farm/'

_agent = LOCAL.get('agent') or {}
AGENT_WORKER_ID = _agent.get('worker_id') or 'this-pc'
AGENT_TOKEN = _agent.get('token') or ''
AGENT_TITLE = _agent.get('title') or 'Этот ПК'
AGENT_POLL_SEC = 4
HEARTBEAT_SEC = int(LOCAL.get('heartbeat_sec') or 60)
STALL_MINUTES = int(LOCAL.get('stall_minutes') or 5)
OPEN_GRACE_SEC = int(LOCAL.get('open_grace_sec') or 120)
SOLVER_TOKEN = LOCAL.get('solver_token') or ''
SOLVER_UPSTREAM = LOCAL.get('solver_upstream') or 'https://api.sbcsolver.com'
TELEGRAM_TOKEN = LOCAL.get('telegram_token') or ''
TELEGRAM_CHATS = LOCAL.get('chats') or {}
SOCKS = LOCAL.get('socks') or ''

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'console': {
            'format': '{levelname} {name} {message}',
            'style': '{',
        },
        'journal': {
            'format': '{asctime} {levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'console',
        },
        'journal': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(BASE_DIR / 'logs' / 'farm_journal.log'),
            'maxBytes': 1024 * 1024,
            'backupCount': 3,
            'encoding': 'utf-8',
            'formatter': 'journal',
        },
    },
    'loggers': {
        'farm_journal': {
            'handlers': ['journal'],
            'level': 'INFO',
            'propagate': True,
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
