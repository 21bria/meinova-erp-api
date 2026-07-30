from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("SECRET_KEY", default="django-insecure-dev-only")

DEBUG = config("DEBUG", default=True, cast=bool)

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1,.localhost,erp.localhost",
).split(",")

AUTH_USER_MODEL = "accounts.User"


SHARED_APPS = [
    "django_tenants",
    "apps.tenants.apps.TenantsConfig",


    # "daphne",  # taruh di paling atas, sebelum django.contrib.staticfiles
    # "channels",

    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    "corsheaders",
    # "django_celery_beat",
    # "django_celery_results",  
]

TENANT_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",

    "rest_framework",
    "rest_framework_simplejwt",
    "django_filters",
    "drf_spectacular",
    

    "apps.accounts.apps.AccountsConfig",
    "apps.framework.apps.FrameworkConfig",
    "apps.core.apps.CoreConfig",
    "apps.administration.apps.AdministrationConfig",

    "apps.assets.apps.AssetsConfig",
    "apps.hr.apps.HrConfig",
    "apps.payroll.apps.PayrollConfig",
    "apps.scm.apps.ScmConfig",
    "apps.finance.apps.FinanceConfig",
    "apps.reports.apps.ReportsConfig",
]

INSTALLED_APPS = SHARED_APPS + [
    app for app in TENANT_APPS
    if app not in SHARED_APPS
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",

    "django_tenants.middleware.main.TenantMainMiddleware",

    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),

    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticatedOrReadOnly",
    ),

    "DEFAULT_RENDERER_CLASSES": (
        "rest_framework.renderers.JSONRenderer",
    ),

    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),

    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",

    "DEFAULT_PAGINATION_CLASS": (
        "apps.core.pagination.StandardPagination"
    ),
    "PAGE_SIZE": 20,

    "EXCEPTION_HANDLER": (
        "apps.core.exceptions.handler."
        "meinova_exception_handler"
    ),
}

ROOT_URLCONF = "config.urls"
PUBLIC_SCHEMA_URLCONF = "config.urls"


CORS_ALLOW_ALL_ORIGINS = True

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

WSGI_APPLICATION = 'config.wsgi.application'

# Database
DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
    }
}

DATABASE_ROUTERS = (
    "django_tenants.routers.TenantSyncRouter",
)

TENANT_MODEL = "tenants.Client"  # app.Model
TENANT_DOMAIN_MODEL = "tenants.Domain"

PUBLIC_SCHEMA_NAME = "public"               # default
SHOW_PUBLIC_IF_NO_TENANT_FOUND = True       # opsional


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

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
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# django-tenants media
DEFAULT_FILE_STORAGE = "django_tenants.files.storage.TenantFileSystemStorage"
MULTITENANT_RELATIVE_MEDIA_ROOT = "%s"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redis / Celery
REDIS_URL = config("REDIS_URL", default="redis://localhost:6379/0")

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

# Celery Beat (scheduled tasks) — simpan schedule di DB, bukan hardcode di file
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# Cache pakai Redis juga (beda db index dari celery biar nggak campur)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": config("REDIS_CACHE_URL", default="redis://localhost:6379/1"),
    }
}

# ASGI_APPLICATION = "config.asgi.application"

# CHANNEL_LAYERS = {
#     "default": {
#         "BACKEND": "channels_redis.core.RedisChannelLayer",
#         "CONFIG": {
#             "hosts": [config("REDIS_CHANNELS_URL", default="redis://localhost:6379/2")],  # ← ganti nama env var-nya
#         },
#     },
# }