from pathlib import Path

from celery.schedules import crontab
from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = config("SECRET_KEY", default="django-insecure-dev-only")

# `MEINOVA_AGENT_API_KEY` (kunci agent global lintas tenant) DIHAPUS di
# SEC-ATT-SYNC-1 dan tidak dibaca di mana pun. Agent kini memakai kredensial
# per device: `manage.py tenant_command attendance_agent_key issue <DEVICE>
# --schema=<tenant>`. Lihat `apps/hr/api/attendance_sync/credentials.py`.

DEBUG = config("DEBUG", default=True, cast=bool)

ALLOWED_HOSTS = config(
    "ALLOWED_HOSTS",
    default="localhost,127.0.0.1,.localhost,erp.localhost",
).split(",")

AUTH_USER_MODEL = "accounts.User"

# `RolePermissionBackend` yang membuat centang di layar Roles benar-benar
# berlaku — tanpa itu `Role.permissions` cuma data mati, karena
# `ModelBackend` bawaan hanya membaca `user_permissions` dan `groups`.
# `ModelBackend` tetap dipertahankan: dia yang mengautentikasi saat login.
AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.RolePermissionBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Saklar penjagaan izin per model (lihat `apps.accounts.permissions`).
# Matikan sementara kalau role di sebuah tenant belum diisi — menyalakannya
# di tenant yang rolenya kosong membuat seluruh sistem read-only kecuali
# untuk superuser. Urutan yang benar: `tenant_command seed_security_roles`
# dulu, baru dinyalakan.
ENFORCE_MODEL_PERMISSIONS = config(
    "ENFORCE_MODEL_PERMISSIONS",
    default=True,
    cast=bool,
)

# Saklar penjagaan **baca** per model. Berbeda dari yang di atas: yang
# ini hanya berlaku pada resource yang menyatakan dirinya sensitif lewat
# `require_view_permission`, bukan pada seluruh endpoint.
#
# Dipisah dari `ENFORCE_MODEL_PERMISSIONS` karena urutan menyalakannya
# berbeda. Izin tulis sudah lama diseed; izin **baca** belum — sebelum
# `seed_security_roles` versi ini dijalankan, tidak satu pun role selain
# SYSTEM-ADMIN punya `view_*` untuk payroll, jadi menyalakan penjagaan
# ini lebih dulu mengunci seluruh operator payroll dari payroll.
#
# Urutan yang benar sama seperti saudaranya: `tenant_command
# seed_security_roles` dulu, baru dinyalakan.
ENFORCE_VIEW_PERMISSIONS = config(
    "ENFORCE_VIEW_PERMISSIONS",
    default=True,
    cast=bool,
)

# Cakupan data dihitung **per izin**, bukan per orang.
#
# Tanpa ini, izin dari satu role berjalan sejauh gabungan cakupan
# seluruh role pemegangnya: Executive yang memegang `EMPLOYEE` demi slip
# gajinya sendiri membaca slip semua orang di cakupan Executive-nya.
#
# **Bawaannya menyala sejak 20 Sep 2026**, dan itu perubahan bawaan
# yang disengaja: sejak cakupan tulis dihitung dari izin tulis
# (`required_scope_permission`), saklar yang mati berarti PATCH dan
# DELETE kembali memakai gabungan seluruh role — pemegang dua role bisa
# menyetujui dan menghapus dokumen orang lain. Bawaan yang tidak aman
# bukan bawaan yang boleh menunggu.
#
# Urutannya tetap sama sebelum sebuah tenant dinyalakan: seed izinnya
# (`seed_security_roles`), buktikan cakupannya
# (`audit_role_aware_coverage`, `--writes` untuk sisi tulis), baru
# dirilis. Untuk tenant `demo`: **0 HILANG, 0 NAIK, 0 SEMPIT** pada
# 2.546 pasangan (akun × izin tulis) — yang menyempit hanyalah akun
# yang memang tidak memegang izinnya (sudah ditolak `ModelPermission`)
# dan akun bercakupan `own` yang memang belum punya baris.
#
# **Env var dipertahankan untuk rollback.** `ROLE_AWARE_DATA_SCOPE=0`
# mengembalikan perilaku lama tanpa rilis ulang — satu-satunya alasan
# jalur lamanya masih ada. Begitu setiap tenant produksi terbukti aman,
# saklarnya dicabut bersama jalur lamanya di `DataScopeService`.
ROLE_AWARE_DATA_SCOPE = config(
    "ROLE_AWARE_DATA_SCOPE",
    default=True,
    cast=bool,
)

# Penyaringan data per baris (`apps.accounts.scoping`): baris yang kolom
# cakupannya kosong ikut terlihat atau tidak. Bawaannya **tidak** — di
# struktur ini hanya Company yang wajib, jadi membiarkan NULL lolos
# berarti siapa pun yang lupa mengisi lokasi membuat datanya terbuka
# untuk semua role. Risiko sebaliknya juga nyata: data berlokasi kosong
# jadi tak terlihat siapa pun kecuali superuser, tanpa pesan.
DATA_SCOPE_INCLUDE_NULL = config(
    "DATA_SCOPE_INCLUDE_NULL",
    default=False,
    cast=bool,
)

# Tap kehadiran Self Service (`POST /api/me/attendance/punch/`).
# **Mati bawaannya.** Menyalakannya saja tidak cukup: selama pemeriksaan
# yang diwajibkan kebijakan (wajah, liveness, geofence) belum punya mesin
# terpasang, endpoint tetap menjawab UNAVAILABLE — gagal tertutup.
# Detail: `docs/claude/hr/attendance-self-punch.md`.
ATTENDANCE_SELF_PUNCH_ENABLED = config(
    "ATTENDANCE_SELF_PUNCH_ENABLED",
    default=False,
    cast=bool,
)

# Jeda minimum antara tap yang DITERIMA dan tap berikutnya (detik),
# penahan tap ganda tak sengaja. 0 = mati.
ATTENDANCE_SELF_PUNCH_MIN_INTERVAL_SECONDS = config(
    "ATTENDANCE_SELF_PUNCH_MIN_INTERVAL_SECONDS",
    default=60,
    cast=int,
)

# Akurasi GPS terburuk (meter) yang masih diterima pemeriksaan lokasi.
ATTENDANCE_SELF_PUNCH_MAX_GPS_ACCURACY_METERS = config(
    "ATTENDANCE_SELF_PUNCH_MAX_GPS_ACCURACY_METERS",
    default=100,
    cast=int,
)

# Uji coba GPS Self Service (ATT-GPS-1): daftar **nama schema tenant**,
# dipisah koma, mis. `ATTENDANCE_SELF_PUNCH_TRIAL_SCHEMAS=demo`. Kosong
# bawaannya. Di tenant yang terdaftar, tap lewat lokasi + geofence dan
# selfie disimpan sebagai bukti, tapi wajah/liveness tetap belum terpasang
# dan tap **tidak pernah** menjadi kehadiran. Pola (`*`) dan schema publik
# diabaikan. Tenant lain tidak terpengaruh sama sekali.
ATTENDANCE_SELF_PUNCH_TRIAL_SCHEMAS = config(
    "ATTENDANCE_SELF_PUNCH_TRIAL_SCHEMAS",
    default="",
    cast=Csv(),
)


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
    "django_celery_beat",
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


    "apps.imports.apps.ImportsConfig",
    "apps.uploads.apps.UploadsConfig",
    "apps.assets.apps.AssetsConfig",
    "apps.hr.apps.HrConfig",
    "apps.payroll.apps.PayrollConfig",
    "apps.scm.apps.ScmConfig",
    "apps.finance.apps.FinanceConfig",
    "apps.reports.apps.ReportsConfig",
    "apps.workflow.apps.WorkflowConfig",
    "apps.helpcenter.apps.HelpCenterConfig",
    # Notifikasi generik (in-app + email). Di TENANT_APPS, bukan
    # SHARED_APPS: template, aturan penerima, dan log pengirimannya
    # semuanya data milik tenant masing-masing.
    "apps.notifications.apps.NotificationsConfig",

    # Self Service — lapisan agregasi employee-facing. Di TENANT_APPS
    # karena yang dibacanya data tenant, bukan karena ia memilikinya:
    # app ini sengaja **tanpa model**. Lihat docs/claude/self-service.md.
    "apps.self_service.apps.SelfServiceConfig",
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

    # Menyimpan user, IP, dan user agent request yang sedang berjalan.
    # Wajib **sesudah** AuthenticationMiddleware — sebelum itu
    # `request.user` belum ada, dan jejak auditnya jadi anonim semua.
    "apps.core.middleware.current_user.CurrentRequestMiddleware",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        # JWT yang terikat tenant — lihat `apps.accounts.jwt`.
        "apps.accounts.jwt.TenantJWTAuthentication",
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

# Refresh token juga terikat tenant: refresh di host tenant lain ditolak
# sebelum User dicari. Kunci lain tetap bawaan SimpleJWT.
SIMPLE_JWT = {
    "TOKEN_REFRESH_SERIALIZER": "apps.accounts.jwt.TenantTokenRefreshSerializer",
}

ROOT_URLCONF = "config.urls"
PUBLIC_SCHEMA_URLCONF = "config.urls"


CORS_ALLOW_ALL_ORIGINS = True

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        # Kerangka HTML email tinggal di sini (`templates/email/`).
        #
        # Yang disunting orang dari layar adalah **isi** pesannya; yang
        # membungkusnya — kop, warna, kaki surat, gaya yang membuatnya
        # terbaca di Outlook — tetap di repo. Menyerahkan seluruh HTML
        # ke kolom database berarti tiap tenant yang menyunting satu
        # kalimat berisiko merusak tata letak seluruh emailnya, dan
        # rusaknya baru terlihat di kotak masuk penerima.
        'DIRS': [BASE_DIR / "templates"],
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

# Bahasa antarmuka yang didukung.
#
# **Sumber kebenaran untuk kolom `User.language`** — pilihan kolom itu
# diturunkan dari daftar ini, jadi menambah bahasa ketiga cukup dengan
# menambah satu baris di sini (plus katalog pesannya di frontend).
#
# Kodenya sengaja pendek dan **stabil**: nilai inilah yang tersimpan di
# database dan dikirim API. Nama bahasanya boleh berubah; kodenya tidak.
LANGUAGES = [
    ("en", "English"),
    ("id", "Bahasa Indonesia"),
]

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True

# `TIME_ZONE` di atas **tidak** ikut bergerak saat bahasa pengguna
# berubah, dan itu disengaja. Bahasa menentukan kata; zona waktu
# menentukan jam. Menggabungkannya berarti pegawai yang mengganti
# antarmukanya ke Bahasa Indonesia mendapati jam absensinya bergeser.


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

from .uploads import *
from .storage import *


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redis / Celery
REDIS_URL = config(
    "REDIS_URL",
    default="redis://localhost:6379/0",
)

CELERY_BROKER_URL = REDIS_URL

CELERY_RESULT_BACKEND = config(
    "CELERY_RESULT_BACKEND",
    default="redis://localhost:6379/3",
)

CELERY_ACCEPT_CONTENT = [
    "json",
]

CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
# Zona **jadwal**, sengaja lepas dari `TIME_ZONE` yang UTC.
#
# `TIME_ZONE` menentukan cara timestamp disimpan dan dirender, dan itu
# benar tetap UTC. Tapi jadwal ditulis dalam jam kerja orang: "kirim
# pengingat jam 6 pagi" berarti jam 6 di tempat pegawainya bekerja, dan
# dengan UTC entri itu jalan jam 1 siang tanpa ada yang menyadarinya —
# jadwalnya "benar" menurut berkas konfigurasi.
CELERY_TIMEZONE = config(
    "CELERY_TIMEZONE",
    default="Asia/Jakarta",
)

CELERY_TASK_TRACK_STARTED = True

CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True

CELERY_WORKER_PREFETCH_MULTIPLIER = 1

CELERY_TASK_SOFT_TIME_LIMIT = 3300
CELERY_TASK_TIME_LIMIT = 3600

CELERY_BROKER_TRANSPORT_OPTIONS = {
    "visibility_timeout": 7200,
}

CELERY_RESULT_EXPIRES = 86400

# Celery Beat
#
# Jadwalnya di tabel (`DatabaseScheduler`), bukan di berkas: tenant yang
# ingin pengingatnya jam 6 pagi tidak boleh perlu menunggu rilis. Entri
# di `CELERY_BEAT_SCHEDULE` di bawah cuma nilai awal — beat menyalinnya
# ke tabel saat pertama kali jalan, dan sesudah itu tabelnya yang
# berlaku.
#
# Tabelnya ada di **public schema** (`django_celery_beat` masuk
# `SHARED_APPS`), jadi satu penjadwal melayani semua tenant. Karena itu
# tasknya sendiri yang mengambil daftar tenant dan menyebar per schema —
# bukan satu entri jadwal per tenant.
CELERY_BEAT_SCHEDULER = (
    "django_celery_beat.schedulers:"
    "DatabaseScheduler"
)

CELERY_BEAT_SCHEDULE = {
    # Sekali sehari, pagi sebelum jam kerja. Pengingat kontrak yang
    # datang tengah hari sudah terlambat setengah hari kerja.
    "employee-reminders-daily": {
        "task": "hr.dispatch_employee_reminders",
        "schedule": crontab(hour=6, minute=0),
    },

    # Pengingat kedaluwarsa saldo cuti. Sengaja **setelah** pengingat
    # kepegawaian: keduanya menyebar per tenant, dan menjalankannya di
    # menit yang sama membuat dua gelombang task berebut worker yang
    # sama tanpa alasan.
    "leave-expiry-reminders-daily": {
        "task": "hr.dispatch_leave_expiry_reminders",
        "schedule": crontab(hour=6, minute=30),
    },

    # Pengingat keberangkatan Travel Request. Lebih siang karena yang
    # dikirim menyangkut hari itu juga dan bukan pekerjaan administratif
    # yang perlu disiapkan sejak pagi.
    "travel-departure-reminders-daily": {
        "task": "hr.dispatch_travel_reminders",
        "schedule": crontab(hour=7, minute=0),
    },

    # Business Trip yang tanggal berangkatnya tiba ditandai ON_TRIP.
    # Tengah malam lewat sedikit — status harian, bukan pengingat.
    "business-trip-departures-daily": {
        "task": "hr.dispatch_business_trip_departures",
        "schedule": crontab(hour=0, minute=15),
    },
}

# Antrean per jenis pekerjaan.
#
# Tanpa routing, email mendarat di antrean yang sama dengan job import —
# dan satu berkas absensi 20.000 baris menahan pemberitahuan approval di
# belakangnya selama berjam-jam. Workernya dijalankan terpisah dari
# image yang sama:
#
#     celery -A config worker -Q celery -l info
#     celery -A config worker -Q notifications -l info -c 4
CELERY_TASK_ROUTES = {
    "notifications.*": {"queue": "notifications"},
}

# Role yang menerima pengingat tanggal kepegawaian.
#
# Di settings, bukan ditanam di kode, dengan alasan yang sama seperti
# `WORKFLOW_MONITOR_ROLES`: tenant yang menamai role-nya berbeda tidak
# perlu menunggu rilis. Yang diterima tiap orang tetap disaring
# cakupan data — admin site tidak menerima pengingat kontrak
# pegawai kantor pusat.
HR_REMINDER_ROLES = config(
    "HR_REMINDER_ROLES",
    default="HR-ADMIN,HR-MANAGER,HRGA",
    cast=lambda value: [
        item.strip()
        for item in str(value).split(",")
        if item.strip()
    ],
)

# Employee Group yang tombol "Lokasi Saya"-nya berarti **seluruh lokasi
# dalam cakupannya**, bukan lokasi penempatannya sendiri.
#
# Direksi duduk di satu kantor tapi bertanggung jawab atas seluruh
# grup. Tombol yang menyempitkan layarnya ke satu baris Location
# menjawab pertanyaan yang bukan pertanyaannya — dan di tenant berisi
# dua belas perusahaan, mencentang lokasinya satu per satu bukan
# pekerjaan yang masuk akal untuk dilakukan tiap kali membuka laporan.
#
# Di settings, bukan ditanam di kode, dengan alasan yang sama seperti
# `HR_REMINDER_ROLES`: tenant yang menamai group-nya berbeda (`BOD`,
# `DIREKSI`, `BOARD`) tidak perlu menunggu rilis.
#
# **Ini kenyamanan, bukan wewenang.** Yang dipilih tombolnya tetap
# lewat `DataScopeService`, jadi group ini tidak menambah satu baris
# pun yang boleh dilihat pemegangnya.
BOARD_EMPLOYEE_GROUPS = config(
    "BOARD_EMPLOYEE_GROUPS",
    default="BOARD,BOD",
    cast=lambda value: [
        item.strip().upper()
        for item in str(value).split(",")
        if item.strip()
    ],
)

# Cache
CACHES = {
    "default": {
        "BACKEND": (
            "django.core.cache.backends.redis."
            "RedisCache"
        ),
        "LOCATION": config(
            "REDIS_CACHE_URL",
            default="redis://localhost:6379/1",
        ),
    },
}

# ASGI_APPLICATION = "config.asgi.application"

# CHANNEL_LAYERS = {
#     "default": {
#         "BACKEND": (
#             "channels_redis.core."
#             "RedisChannelLayer"
#         ),
#         "CONFIG": {
#             "hosts": [
#                 config(
#                     "REDIS_CHANNELS_URL",
#                     default=(
#                         "redis://localhost:6379/2"
#                     ),
#                 )
#             ],
#         },
#     },
# }

# Setelan email & notifikasi.
#
# Di-import paling akhir supaya nilai di sana bisa merujuk apa pun yang
# sudah didefinisikan di atas, dan supaya seluruhnya terkumpul di satu
# berkas alih-alih terselip di antara setelan lain.
from .email import *  # noqa: E402,F401,F403
