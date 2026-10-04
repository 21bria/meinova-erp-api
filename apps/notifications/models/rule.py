"""
Aturan penerima per event.

**Satu baris = satu kelompok penerima**, bukan satu baris berisi daftar
role. Bentuknya sengaja disamakan dengan `WorkflowStep`: orang yang
mengatur alur persetujuan dan orang yang mengatur penerima notifikasi
adalah orang yang sama, dan satu baris per meja sudah terbukti bisa
diisi dari layar yang ada.

Alasan teknisnya juga sama dengan `EmployeeDataPolicy.role`: M2M ke Role
berarti kolom yang **tidak bisa diisi dari layar mana pun**, karena
`MMultiLookupField` baru dirender `MRecordActions` dan belum
`MFormBuilder`. Dua role penerima = dua baris, dan itu justru lebih
terbaca: masing-masing punya kanalnya sendiri, jadi HR boleh dapat email
sementara atasan langsung cukup notifikasi bel.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from ..constants import RecipientType


class NotificationRule(BaseModel):
    """
    Satu kelompok penerima untuk satu event.

    **Event tanpa satu baris pun memakai bawaan dari registry**, bukan
    berarti "tidak ada yang menerima". Aturan yang sama dengan role
    tanpa baris menu dan role tanpa baris cakupan di codebase ini —
    dan konsekuensinya sama: bawaan yang berubah besok tetap sampai ke
    tenant yang belum pernah mengaturnya, karena bawaannya tidak pernah
    ditulis ke database.

    Yang sengaja mematikan seluruh penerima tetap bisa: buat satu baris
    lalu matikan `is_active`. Pembedanya **ada barisnya**, bukan **ada
    yang aktif** — pelajaran yang sama dengan `FavoriteApp.set_favorites`.
    """

    event = models.CharField(
        max_length=100,
        db_index=True,
        help_text="Kode event dari registry notifikasi.",
    )

    company = models.ForeignKey(
        "administration.Company",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notification_rules",
        help_text=(
            "Dikosongkan = berlaku untuk semua company. Baris yang "
            "menyebut company mengalahkan yang global — dan begitu ada "
            "satu baris bercompany, baris global tidak dipakai lagi "
            "untuk company itu."
        ),
    )

    # ------------------------------------------------------------------
    # Penerima
    # ------------------------------------------------------------------

    recipient_type = models.CharField(
        max_length=30,
        choices=RecipientType.choices,
        default=RecipientType.SUBJECT,
    )

    role = models.ForeignKey(
        "accounts.Role",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notification_rules",
        help_text=(
            "Wajib kalau penerimanya Pemegang Role. Yang diterima "
            "masing-masing tetap disaring cakupan datanya — admin site "
            "tidak menerima pemberitahuan pegawai kantor pusat."
        ),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notification_rules",
        help_text="Wajib kalau penerimanya Pengguna Tertentu.",
    )

    manager_level = models.PositiveSmallIntegerField(
        default=1,
        help_text=(
            "Berapa tingkat naik dari pegawai bersangkutan. 1 = atasan "
            "langsung, 2 = atasannya atasan. Hanya berlaku untuk "
            "penerima bertipe Atasan Langsung."
        ),
    )

    # ------------------------------------------------------------------
    # Kanal
    # ------------------------------------------------------------------
    #
    # Dua penanda, bukan satu daftar JSON: keduanya jadi kolom yang bisa
    # disaring di tabel ("aturan mana saja yang mengirim email"), dan
    # `field.switch()` sudah dirender di form. Daftar JSON berarti satu
    # kolom yang tidak bisa disaring dan tidak bisa diisi dari layar.

    send_in_app = models.BooleanField(
        default=True,
        help_text="Tulis ke bel notifikasi dalam aplikasi.",
    )

    send_email = models.BooleanField(
        default=True,
        help_text=(
            "Kirim email. Tetap tunduk pada setelan masing-masing "
            "penerima — yang mematikan email di profilnya tidak "
            "dipaksa menerimanya."
        ),
    )

    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "notification_rule"
        ordering = ["event", "sort_order", "id"]

        constraints = [
            models.UniqueConstraint(
                fields=["event", "company", "recipient_type", "role", "user"],
                condition=Q(is_deleted=False),
                name="uniq_active_notification_rule",
            ),
        ]

        indexes = [
            models.Index(fields=["event", "is_active"]),
        ]

    def __str__(self):
        return f"{self.event} → {self.get_recipient_type_display()}"

    def clean(self):
        super().clean()

        errors = {}

        if self.recipient_type == RecipientType.ROLE and not self.role_id:
            errors["role"] = (
                "Pilih role-nya. Penerima bertipe Pemegang Role tanpa "
                "role yang disebut tidak akan pernah menemukan siapa pun, "
                "dan gagalnya diam."
            )

        if self.recipient_type == RecipientType.USER and not self.user_id:
            errors["user"] = "Pilih penggunanya."

        # Baris yang kedua kanalnya mati adalah baris yang tidak
        # melakukan apa-apa, dan di layar ia terbaca seperti penerima
        # yang seharusnya menerima sesuatu. Yang mau menonaktifkan
        # sementara memakai `is_active`.
        if not self.send_in_app and not self.send_email:
            errors["send_in_app"] = (
                "Pilih minimal satu kanal, atau matikan barisnya lewat "
                "Active."
            )

        if errors:
            raise ValidationError(errors)

    # ------------------------------------------------------------------

    @classmethod
    def resolve(cls, event: str, *, company=None) -> list["NotificationRule"]:
        """
        Aturan yang berlaku untuk satu event.

        Baris bercompany menang **seluruhnya** atas baris global, bukan
        digabung. Menggabungkannya membuat company yang sengaja
        mempersempit penerimanya tetap kebagian penerima global, dan
        tidak ada cara menyatakan "untuk perusahaan ini, cukup HR-nya
        saja".

        Daftar kosong berarti "belum diatur" — pemanggilnya yang jatuh
        ke bawaan registry. Itu berbeda dari daftar berisi baris yang
        semuanya tidak aktif, yang memang berarti "sengaja tidak ada
        yang menerima".
        """
        code = str(event).strip().lower()

        base = cls.objects.filter(event=code, is_deleted=False)

        company_id = getattr(company, "pk", company)

        if company_id:
            scoped = list(
                base.filter(company_id=company_id)
                .select_related("role", "user")
            )

            if scoped:
                return [row for row in scoped if row.is_active]

        rows = list(
            base.filter(company__isnull=True).select_related("role", "user")
        )

        return [row for row in rows if row.is_active]

    @classmethod
    def is_configured(cls, event: str, *, company=None) -> bool:
        """
        Apakah tenant sudah pernah mengatur event ini.

        Dipisah dari `resolve()` karena pembedanya **ada barisnya**,
        bukan ada yang aktif — dan itu yang menentukan jatuh ke bawaan
        registry atau tidak.
        """
        code = str(event).strip().lower()
        base = cls.objects.filter(event=code, is_deleted=False)

        company_id = getattr(company, "pk", company)

        if company_id and base.filter(company_id=company_id).exists():
            return True

        return base.filter(company__isnull=True).exists()
