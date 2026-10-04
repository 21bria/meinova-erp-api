from .base import *

DEBUG = True

# Cakupan data dihitung per izin, bukan per orang.
#
# **Sudah jadi bawaan `base.py` sejak 20 Sep 2026** — baris ini tinggal
# penegasan supaya pengembangan tidak pernah berjalan pada perilaku
# lama, bukan lagi satu-satunya tempat saklar ini menyala.
#
# Dibuktikan untuk tenant `demo` lewat
# `manage.py tenant_command audit_role_aware_coverage --writes --schema=demo`:
# sisi baca 23 PINJAM / 0 HILANG, sisi tulis 0 HILANG / 0 SEMPIT / 0 NAIK.
ROLE_AWARE_DATA_SCOPE = True

# `ALLOWED_HOSTS` **tidak** ditimpa di sini.
#
# Dulu berkas ini menyetel ulang daftarnya setelah `from .base import *`,
# jadi nilai dari `.env` selalu terbuang. Akibatnya tidak kelihatan
# seperti kesalahan host: `TenantMainMiddleware` menangkap
# `DisallowedHost` dan mengembalikan `HttpResponseNotFound()` kosong,
# sehingga host yang tidak terdaftar terbaca sebagai **404 rute salah**,
# bukan 400 host ditolak. Itu yang menyembunyikan penyebab saat host LAN
# `demo.192.168.2.206.nip.io` ditambahkan ke `.env` (23 Sep 2026).
#
# Daftarnya sekarang satu sumber saja: `ALLOWED_HOSTS` di `.env`, dibaca
# `base.py` — yang defaultnya sudah memuat localhost/127.0.0.1/
# .localhost/erp.localhost untuk mesin yang belum punya `.env`.