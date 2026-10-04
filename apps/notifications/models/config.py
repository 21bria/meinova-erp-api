"""
Setelan notifikasi tingkat tenant.

Satu baris per tenant, bukan per company — SMTP, nama pengirim, dan
alamat frontend memang milik tenant. Bandingkan dengan `TenantSetting`
dan `PrintSetting` yang justru `OneToOne(company)`: yang membedakan
apakah nilainya ikut berganti saat dokumen berpindah perusahaan. Alamat
aplikasi tidak.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.core.models.base import BaseModel


class NotificationConfig(BaseModel):
    """
    Identitas pengirim dan saklar tingkat tenant.

    Dibuat saat dibaca (`resolve()`), bukan lewat migrasi data — pola
    yang sama dengan `EmployeeReminderPolicy.resolve()`. Tenant baru
    tidak boleh kehilangan seluruh emailnya hanya karena satu perintah
    seed belum dijalankan.
    """

    name = models.CharField(max_length=100, default="Default")

    # ------------------------------------------------------------------
    # Saklar
    # ------------------------------------------------------------------

    email_enabled = models.BooleanField(
        default=True,
        help_text=(
            "Saklar induk email untuk tenant ini. Dimatikan = seluruh "
            "email dilewati dan dicatat di log sebagai dilewati, bukan "
            "hilang tanpa jejak."
        ),
    )

    in_app_enabled = models.BooleanField(
        default=True,
        help_text="Saklar induk notifikasi dalam aplikasi (bel).",
    )

    # ------------------------------------------------------------------
    # Identitas pengirim
    # ------------------------------------------------------------------

    sender_name = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text=(
            "Nama yang tampil sebagai pengirim. Dikosongkan = memakai "
            "nama aplikasi. Alamatnya sendiri tetap dari setelan server "
            "(DEFAULT_FROM_EMAIL) — mengarang alamat pengirim per tenant "
            "membuat emailnya ditolak SPF di sisi penerima."
        ),
    )

    reply_to = models.EmailField(
        blank=True,
        default="",
        help_text=(
            "Alamat balasan, mis. hrd@perusahaan.co.id. Ini yang "
            "membuat email sistem bisa dibalas ke orang sungguhan — "
            "tanpa itu balasan mendarat di kotak no-reply yang tidak "
            "dibuka siapa pun."
        ),
    )

    # ------------------------------------------------------------------
    # Tampilan
    # ------------------------------------------------------------------

    app_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text=(
            "Nama aplikasi di kop dan kaki email. Dikosongkan = "
            "Meinova ERP."
        ),
    )

    logo_url = models.URLField(
        blank=True,
        default="",
        help_text=(
            "Alamat penuh logo di kop email. Wajib absolut dan bisa "
            "diakses tanpa login — klien email tidak membawa sesi "
            "penerimanya, jadi jalur relatif dan berkas di balik "
            "autentikasi tampil sebagai gambar rusak."
        ),
    )

    base_url = models.URLField(
        blank=True,
        default="",
        help_text=(
            "Alamat frontend tenant ini, mis. https://demo.meinova.id. "
            "Dipakai membangun tautan di dalam email. Dikosongkan = "
            "memakai jatuhan di settings, dan tautannya bisa mendarat "
            "di tenant lain."
        ),
    )

    footer_text = models.TextField(
        blank=True,
        default="",
        help_text=(
            "Kalimat di kaki setiap email. Tempat menaruh keterangan "
            "'email ini dikirim otomatis' dan kontak yang bisa "
            "dihubungi."
        ),
    )

    class Meta:
        db_table = "notification_config"
        ordering = ["name"]

    def __str__(self):
        return self.name

    # ------------------------------------------------------------------

    @property
    def resolved_app_name(self) -> str:
        return self.app_name or "Meinova ERP"

    @property
    def resolved_base_url(self) -> str:
        return (
            self.base_url
            or getattr(settings, "NOTIFICATION_DEFAULT_BASE_URL", "")
        ).rstrip("/")

    @property
    def resolved_sender(self) -> str:
        """
        Header `From` yang siap pakai.

        Nama boleh diganti tenant, alamatnya tidak — lihat help text
        `sender_name`. Kalau nama mengandung koma, `formataddr` yang
        mengutipnya; tanpa itu satu nama seperti "PT Meinova, Tbk"
        memecah header jadi dua alamat.
        """
        from email.utils import formataddr

        address = getattr(settings, "DEFAULT_FROM_EMAIL", "")

        if not address:
            return ""

        return formataddr(
            (self.sender_name or self.resolved_app_name, address),
        )

    @classmethod
    def resolve(cls) -> "NotificationConfig":
        """Setelan yang berlaku, dibuatkan bawaan kalau belum ada."""
        instance = (
            cls.objects
            .filter(is_deleted=False)
            .order_by("id")
            .first()
        )

        if instance is None:
            instance = cls.objects.create(name="Default")

        return instance
