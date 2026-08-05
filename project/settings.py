from pathlib import Path
import dj_database_url
import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)

# Load .env safely
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

# Fallback prevents crash if .env is missing
SECRET_KEY = env(
    "SECRET_KEY",
    default="x9@7!p4#k2^m8&z1$q6*w3!n5%r8@t2^y4#u7"
)

DEBUG = env("DEBUG")
ALLOWED_HOSTS = [host.strip() for host in env('ALLOWED_HOSTS', default='127.0.0.1,localhost').split(',') if host.strip()]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'storages',
    'accounts',
    'pilot',
    'airspace',
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

ROOT_URLCONF = 'project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
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

WSGI_APPLICATION = 'project.wsgi.application'
ASGI_APPLICATION = 'project.asgi.application'

DATABASES = {
    'default': dj_database_url.parse(
        env('DATABASE_URL', default=f"postgresql://postgres:postgres@127.0.0.1:5432/airspace_local"),
        conn_max_age=env.int('CONN_MAX_AGE', default=60),
        ssl_require=env.bool('DB_SSL_REQUIRE', default=False),
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'America/Indiana/Indianapolis'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'accounts.User'

LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = 'accounts:pilot_profile_onboarding'
LOGOUT_REDIRECT_URL = 'accounts:login'

EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', default='noreply@example.com')
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_HOST = env('EMAIL_HOST', default='')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_USE_SSL = env.bool('EMAIL_USE_SSL', default=False)

USE_S3 = env.bool('USE_S3', default=False)
if USE_S3:
    AWS_ACCESS_KEY_ID = env('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = env('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = env('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME = env('AWS_S3_REGION_NAME')
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = False
    AWS_S3_FILE_OVERWRITE = False

    STORAGES = {
        'default': {
            'BACKEND': 'storages.backends.s3.S3Storage',
            'OPTIONS': {'location': 'media'},
        },
        'staticfiles': {
            'BACKEND': 'storages.backends.s3.S3Storage',
            'OPTIONS': {'location': 'static'},
        },
    }
    STATIC_URL = f"https://{{AWS_STORAGE_BUCKET_NAME}}.s3.{{AWS_S3_REGION_NAME}}.amazonaws.com/static/"
    MEDIA_URL = f"https://{{AWS_STORAGE_BUCKET_NAME}}.s3.{{AWS_S3_REGION_NAME}}.amazonaws.com/media/"

# Invitation-only registration
INVITATION_EXPIRY_HOURS = env.int('INVITATION_EXPIRY_HOURS', default=72)
