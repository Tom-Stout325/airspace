from .settings import *

DEBUG = True
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
USE_S3 = False
