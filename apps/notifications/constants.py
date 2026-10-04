"""
Kosakata bersama modul notifikasi.

Dipisah dari `models.py` supaya `registry.py` bisa memakainya tanpa
menyentuh Django ORM — registry di-import dari `AppConfig.ready()` di
seluruh modul, dan modul yang mendaftarkan event tidak boleh dipaksa
mengimpor model hanya untuk menyebut nama kanal.
"""

from __future__ import annotations

from django.db import models


class Channel(models.TextChoices):
    """
    Kanal pengiriman.

    In-app dan email sengaja **dua baris terpisah** di log, bukan satu
    baris berkanal ganda: yang satu bisa berhasil sementara yang lain
    gagal, dan "notifikasinya sampai atau tidak" harus punya jawaban per
    kanal. Push dan SMS didaftar di sini karena `NotificationSetting`
    sudah lama punya kolomnya — belum ada pengirimnya, dan kanal tanpa
    pengirim ditandai `SKIPPED` dengan alasan yang terbaca, bukan diam.
    """

    IN_APP = "in_app", "In-App"
    EMAIL = "email", "Email"
    PUSH = "push", "Push"
    SMS = "sms", "SMS"


# Kanal yang benar-benar punya pengirim hari ini. Sisanya dilewati
# dengan alasan tertulis di log.
IMPLEMENTED_CHANNELS = frozenset({Channel.IN_APP, Channel.EMAIL})


class RecipientType(models.TextChoices):
    """
    Siapa yang menerima.

    Kosakatanya sengaja dipinjam dari `workflow.ApproverType` — orang
    yang mengatur alur persetujuan dan orang yang mengatur penerima
    notifikasi adalah orang yang sama, dan dua kosakata untuk konsep
    yang sama ("atasan langsung" vs "manager") membuat layar kedua harus
    dipelajari dari nol.

    Empat yang di bawah tidak ada di `ApproverType` karena memang hanya
    bermakna pada notifikasi: `subject` (pegawai yang datanya
    dibicarakan), `submitter` (pengaju), `pending_approver` (yang sedang
    ditagih tanda tangan), dan `preparer` (yang menyiapkan dokumennya).
    """

    SUBJECT = "subject", "Pegawai Bersangkutan"
    SUBMITTER = "submitter", "Pengaju"
    PENDING_APPROVER = "pending_approver", "Approver yang Sedang Ditagih"

    # Yang mengisi meja **pertama** sebuah alur.
    #
    # Bukan sinonim pengaju, dan bedanya justru inti alur site: pegawai
    # yang mengajukan, Admin Section yang menyiapkan dokumennya. Kalau
    # hasil akhirnya cuma sampai ke pengaju, orang yang mengetik dan
    # akan dimintai perbaikannya tidak pernah tahu dokumennya sudah
    # diputuskan — dan yang menagihnya jadi pegawai itu sendiri.
    PREPARER = "preparer", "Penyiap Dokumen"
    MANAGER = "manager", "Atasan Langsung"
    DEPARTMENT_HEAD = "department_head", "Kepala Departemen"
    ROLE = "role", "Pemegang Role"
    USER = "user", "Pengguna Tertentu"


class DeliveryStatus(models.TextChoices):
    """
    Keadaan satu baris log.

    `SKIPPED` sengaja dipisah dari `FAILED`. Keduanya berarti "tidak
    terkirim", tapi yang satu keputusan sistem yang benar (penerimanya
    mematikan email, alamatnya kosong, kanalnya belum ada pengirimnya)
    dan yang satu kesalahan yang harus diperbaiki seseorang. Menyatukan
    keduanya membuat layar log penuh baris merah yang tidak ada yang
    perlu ditindaklanjuti — dan sesudah itu tidak ada yang membacanya
    lagi.
    """

    PENDING = "pending", "Menunggu"
    SENT = "sent", "Terkirim"
    FAILED = "failed", "Gagal"
    SKIPPED = "skipped", "Dilewati"


# Alasan `SKIPPED` yang dipakai berulang. Konstanta, bukan kalimat yang
# diketik ulang di tiap pemanggil: alasan yang sama ditulis tiga cara
# berbeda tidak bisa dikelompokkan di layar log.
SKIP_NO_ADDRESS = "Penerima tidak punya alamat email."
SKIP_USER_DISABLED = "Penerima mematikan kanal ini di setelan notifikasinya."
SKIP_CHANNEL_OFF = "Kanal dimatikan untuk event ini."
SKIP_GLOBAL_OFF = "Pengiriman email dimatikan di setelan sistem."
SKIP_TENANT_OFF = "Pengiriman email dimatikan di setelan tenant."
SKIP_NO_TEMPLATE = "Belum ada template email untuk event ini."
SKIP_NOT_IMPLEMENTED = "Kanal ini belum punya pengirim."
SKIP_DUPLICATE = "Sudah pernah dikirim (kunci dedup sama)."
