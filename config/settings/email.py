"""
Pengiriman email.

Berkas ini sudah lama ada sebagai berkas kosong; sampai sekarang tidak
ada satu baris pun di `apps/` yang memanggil `send_mail`. Jadi seluruh
pemberitahuan sistem ini berhenti di bel dalam aplikasi — dan bel hanya
terbaca oleh orang yang sedang membuka aplikasinya. Pengingat kontrak
yang berakhir dan dokumen yang menunggu tanda tangan justru ditujukan
kepada orang yang **tidak** sedang membukanya.

Di-import dari `base.py` (baris terakhir), jadi seluruh nilai di sini
bisa ditimpa lingkungan lewat `.env` tanpa menyentuh kode.

**Bawaannya sengaja `console`.** Backend SMTP yang salah setel gagal
dengan cara yang paling merugikan di lingkungan pengembangan: email uji
benar-benar terkirim ke alamat sungguhan yang kebetulan ada di data
peragaan. Yang mau mengirim sungguhan mengisi `EMAIL_HOST` di `.env`,
dan itu tindakan yang disengaja.
"""

from decouple import config


# ----------------------------------------------------------------------
# Backend
# ----------------------------------------------------------------------

EMAIL_BACKEND = config(
    "EMAIL_BACKEND",default="django.core.mail.backends.console.EmailBackend",
)

EMAIL_HOST = config("EMAIL_HOST", default="localhost")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)

EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")

# TLS dan SSL saling meniadakan — Django melempar kalau keduanya menyala.
# Dipisah jadi dua variabel karena penyedia SMTP memang menawarkan
# keduanya di port berbeda (587 STARTTLS, 465 SSL implisit).
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_USE_SSL = config("EMAIL_USE_SSL", default=False, cast=bool)

# Batas waktu koneksi, dalam detik.
#
# Tanpa ini `smtplib` menunggu selamanya kalau host-nya menerima koneksi
# lalu diam. Worker notifikasi yang menggantung di satu email menahan
# seluruh antrean di belakangnya, dan gejalanya "email tidak terkirim"
# tanpa satu pun baris error.
EMAIL_TIMEOUT = config("EMAIL_TIMEOUT", default=15, cast=int)

DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL",
    default="no-reply@meinova.id",
)

SERVER_EMAIL = config("SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)


# ----------------------------------------------------------------------
# Notifikasi
# ----------------------------------------------------------------------

# Saklar induk. Mematikannya membuat seluruh kanal email dilewati dan
# **dicatat sebagai dilewati**, bukan diam — supaya "kenapa emailnya
# tidak sampai" punya jawaban di layar log, bukan cuma di berkas
# konfigurasi yang tidak dibuka siapa pun.
NOTIFICATION_EMAIL_ENABLED = config(
    "NOTIFICATION_EMAIL_ENABLED",
    default=True,
    cast=bool,
)

# Alamat penampung untuk lingkungan bukan produksi.
#
# Data peragaan memuat alamat email sungguhan (pegawai contoh dibuat
# dari file klien), jadi satu perintah seed yang menembak email nyata ke
# alamat orang lain adalah kesalahan yang tidak bisa ditarik kembali.
# Diisi = seluruh email dialihkan ke sana, alamat aslinya tetap dicatat
# di log pengiriman.
NOTIFICATION_EMAIL_REDIRECT_TO = config(
    "NOTIFICATION_EMAIL_REDIRECT_TO",
    default="",
)

# Antrean Celery khusus notifikasi.
#
# Dipisah dari antrean bawaan supaya SMTP yang lambat tidak menahan job
# import yang sedang berjalan — satu email yang menunggu timeout 15
# detik cukup untuk membuat antrean bersama menumpuk. Workernya
# dijalankan dari image yang sama:
#
#     celery -A config worker -Q notifications -l info
NOTIFICATION_QUEUE = config(
    "NOTIFICATION_QUEUE",
    default="notifications",
)

# Berapa kali satu email diulang sebelum ditandai gagal permanen.
# Kegagalan SMTP lazimnya sementara (rate limit, koneksi putus), jadi
# menyerah di percobaan pertama membuang pemberitahuan yang sebenarnya
# tinggal diulang.
NOTIFICATION_MAX_RETRIES = config(
    "NOTIFICATION_MAX_RETRIES",
    default=3,
    cast=int,
)

NOTIFICATION_RETRY_DELAY = config(
    "NOTIFICATION_RETRY_DELAY",
    default=60,
    cast=int,
)

# Alamat frontend, dipakai membangun tautan di dalam email.
#
# Ini **hanya jatuhan**: alamat yang benar berbeda per tenant (subdomain
# masing-masing) dan tersimpan di `NotificationConfig.base_url` milik
# tenant. Yang di sini dipakai kalau tenant-nya belum mengisi. Tautan
# yang menunjuk host salah mendarat di halaman login tenant lain, dan
# penerimanya menyangka haknya dicabut.
NOTIFICATION_DEFAULT_BASE_URL = config(
    "NOTIFICATION_DEFAULT_BASE_URL",
    default="http://localhost:3000",
)
