from decouple import Csv, config

from .base import *

DEBUG = False

# HTTPS diterminasi Nginx; gunicorn hanya boleh dijangkau lewat Nginx
# (bind 127.0.0.1/unix socket), dan Nginx wajib menimpa header ini:
#   proxy_set_header X-Forwarded-Proto $scheme;
# Kalau gunicorn terbuka langsung, header ini bisa dipalsukan klien.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=True, cast=bool)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# Contoh: https://erp.example.com,https://*.erp.example.com (skema wajib).
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="",
    cast=Csv(),
)

# HSTS sengaja belum dinyalakan (SECURE_HSTS_SECONDS tetap 0).
