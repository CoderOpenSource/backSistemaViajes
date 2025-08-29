"""
Django settings for sistema_boletos project.
"""

from pathlib import Path
from datetime import timedelta
from decouple import config
from decouple import config
import cloudinary
# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Quick-start development settings - unsuitable for production

SECRET_KEY = config('SECRET_KEY', default='unsafe-secret-key')

DEBUG = config('DEBUG', default=False, cast=bool)

CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
]
CORS_ALLOW_CREDENTIALS = True  # si vas a usar cookies; con JWT no es necesario
CSRF_TRUSTED_ORIGINS = ["http://localhost:5173"]  # útil si alguna vista usa CSRF


# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',

    'cloudinary_storage',
    'django.contrib.staticfiles',
    'cloudinary',
    'rest_framework',
    'django_filters',
    'corsheaders',
    'accounts',
    'catalog',
    'passenger',
    'sales'

]

CLOUDINARY_STORAGE = {
    'CLOUD_NAME':  config('CLOUDINARY_CLOUD_NAME'),
    'API_KEY':     config('CLOUDINARY_API_KEY'),
    'API_SECRET':  config('CLOUDINARY_API_SECRET'),
}

# Config explícita para evitar “Must supply api_key”
cloudinary.config(
    cloud_name=CLOUDINARY_STORAGE['CLOUD_NAME'],
    api_key=CLOUDINARY_STORAGE['API_KEY'],
    api_secret=CLOUDINARY_STORAGE['API_SECRET'],
    secure=True,
)

DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'
MEDIA_URL = '/media/'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "accounts.middleware.DBAuditContextMiddleware",
    'accounts.middleware.PasswordExpiryEnforcer'
]

ROOT_URLCONF = 'sistema_boletos.urls'

# settings.py
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        # Si quieres que todas las vistas tengan búsqueda/orden por defecto:
        # 'rest_framework.filters.SearchFilter',
        # 'rest_framework.filters.OrderingFilter',
    ),
    # 👇 Paginación global: 10 por página
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
}

ACCESS_TOKEN_MINUTES = config('ACCESS_TOKEN_MINUTES', cast=int, default=60)   # 1 hora
REFRESH_TOKEN_DAYS   = config('REFRESH_TOKEN_DAYS',   cast=int, default=30)   # 30 días

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=ACCESS_TOKEN_MINUTES),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=REFRESH_TOKEN_DAYS),
    'ROTATE_REFRESH_TOKENS': True,        # opcional
    'BLACKLIST_AFTER_ROTATION': True,     # opcional (necesita app blacklist)
    'AUTH_HEADER_TYPES': ('Bearer',),
}
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

WSGI_APPLICATION = 'sistema_boletos.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='sistema_boletos'),
        'USER': config('DB_USER', default='mosito'),
        'PASSWORD': config('DB_PASS', default='1000'),
        'HOST': config('DB_HOST', default='127.0.0.1'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# Password validation
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

# Internationalization
LANGUAGE_CODE = 'es'

TIME_ZONE = 'America/La_Paz'

USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

AUTH_USER_MODEL = 'accounts.User'
PASSWORD_MAX_AGE_DAYS = 90
REQUIRE_FIRST_LOGIN_CHANGE = False
