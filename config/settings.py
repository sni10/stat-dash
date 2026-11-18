"""Django settings. All environment-specific values come from env vars / .env, validated in config/app_settings."""
import os
from pathlib import Path

from .app_settings import load_settings

BASE_DIR = Path(__file__).resolve().parent.parent

ENV = load_settings(BASE_DIR / '.env')

SECRET_KEY = ENV.django_secret_key.get_secret_value()
DEBUG = ENV.django_debug
ALLOWED_HOSTS = [h.strip() for h in ENV.django_allowed_hosts.split(',') if h.strip()]

# Production: caddy terminates HTTPS and sets X-Forwarded-Proto. Without this Django sees plain HTTP behind it, and the
# login form's CSRF check rejects the https:// Origin. Direct access to the web port (tailnet) sends no such header.
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# CI sets TEST_REPORTS_DIR: tests also write a JUnit report there (unittest-xml-reporting, a dev dependency)
if os.environ.get('TEST_REPORTS_DIR'):
    TEST_RUNNER = 'xmlrunner.extra.djangotestrunner.XMLTestRunner'
    TEST_OUTPUT_DIR = os.environ['TEST_REPORTS_DIR']
    TEST_OUTPUT_FILE_NAME = 'junit.xml'

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.postgres',
    'collector',
    'dashboard',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # admin static from the web container itself
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

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
                'dashboard.context_processors.collection',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': ENV.db_name,
        'USER': ENV.db_user,
        'PASSWORD': ENV.db_password.get_secret_value(),
        'HOST': ENV.db_host,
        'PORT': ENV.db_port,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'uk'
TIME_ZONE = 'Europe/Kyiv'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# One user, the standard Django login (spec, "Веб-интерфейс")
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'overview'
LOGOUT_REDIRECT_URL = 'login'
DASHBOARD_DEFAULT_CITY = ENV.dashboard_default_city

LUN = {
    'BASE_URL': ENV.lun_base_url,
    'PAUSE': (ENV.lun_pause_min, ENV.lun_pause_max),
}
TELEGRAM = {
    'BOT_TOKEN': ENV.telegram_bot_token.get_secret_value(),
    'CHAT_ID': ENV.telegram_chat_id,
}
BACKUP = {
    'DIR': ENV.backup_dir,
    'KEEP': ENV.backup_keep,
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'plain': {'format': '%(asctime)s %(levelname)s %(name)s: %(message)s'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'plain'}},
    'loggers': {'collector': {'handlers': ['console'], 'level': 'INFO'}},
}
