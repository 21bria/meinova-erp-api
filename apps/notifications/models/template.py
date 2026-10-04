"""
Template email per event.

**Isinya di database, bukan berkas .html di repo.** Alasannya sama
dengan Help Center dibalik: yang diseed cuma titik awal, dan tiap klien
akan mengubah kalimatnya sendiri — nama panggilan perusahaan, bahasa,
siapa yang dihubungi kalau ada pertanyaan. Template yang hanya bisa
diubah lewat rilis kode tidak akan pernah diubah siapa pun, dan yang
terkirim ke pegawai klien adalah kalimat yang ditulis programmer.

Yang **tetap** di repo adalah kerangka HTML pembungkusnya
(`templates/email/base.html`): kop, warna, dan gaya yang membuatnya
terbaca di Outlook. Menyerahkan seluruh HTML ke kolom database berarti
satu tenant yang menyunting satu kalimat bisa merusak tata letak seluruh
emailnya, dan rusaknya baru terlihat di kotak masuk penerima.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel


class EmailTemplate(BaseModel):
    """
    Satu template untuk satu event.

    Berjenjang lewat `company`, pola yang sama dengan seluruh policy di
    codebase ini: baris bercompany menang atas yang global, dan
    **kosong berarti "berlaku untuk semua"** — bukan "tidak berlaku".
    Itu jebakan yang paling gampang di layarnya, jadi disebut di help
    text field-nya.
    """

    event = models.CharField(
        max_length=100,
        db_index=True,
        help_text=(
            "Kode event, mis. hr.contract_end. Daftarnya dari registry "
            "notifikasi — event yang tidak terdaftar tidak akan pernah "
            "memicu template ini."
        ),
    )

    company = models.ForeignKey(
        "administration.Company",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="email_templates",
        help_text=(
            "Dikosongkan = berlaku untuk semua company. Baris yang "
            "menyebut company mengalahkan yang global."
        ),
    )

    name = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text="Keterangan untuk pengelola, tidak ikut terkirim.",
    )

    # ------------------------------------------------------------------
    # Isi
    # ------------------------------------------------------------------

    subject = models.CharField(
        max_length=255,
        help_text=(
            "Judul email. Boleh memuat placeholder, mis. "
            "{{ employee_name }}."
        ),
    )

    body = models.TextField(
        help_text=(
            "Isi email. Placeholder ditulis {{ nama_kunci }}; daftar "
            "kunci yang tersedia ada di panel sebelah dan berbeda per "
            "event."
        ),
    )

    # Judul & isi untuk bel dalam aplikasi.
    #
    # Dipisah dari email dan **boleh kosong**: notifikasi bel dibaca
    # sambil lalu di daftar sempit, jadi kalimat pembuka email yang
    # sopan justru membuat isinya terpotong sebelum sampai ke intinya.
    # Kosong = memakai `subject` dan ringkasan pendek dari pemanggil.
    in_app_title = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text=(
            "Judul di bel. Dikosongkan = memakai judul email. Isi "
            "kalau judul emailnya terlalu panjang untuk daftar bel."
        ),
    )

    in_app_body = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Keterangan satu baris di bawah judul bel.",
    )

    class Meta:
        db_table = "notification_email_template"
        ordering = ["event", "company__code"]

        constraints = [
            # Dikondisikan ke `is_deleted`, seperti seluruh kunci unik
            # di codebase ini — kalau tidak, event yang templatenya
            # pernah dihapus tidak akan pernah bisa dibuatkan lagi.
            models.UniqueConstraint(
                fields=["event", "company"],
                condition=Q(is_deleted=False),
                name="uniq_active_email_template_event_company",
            ),
        ]

        indexes = [
            models.Index(fields=["event", "is_active"]),
        ]

    def __str__(self):
        if self.company_id:
            return f"{self.event} ({self.company})"

        return self.event

    def clean(self):
        super().clean()

        errors = {}

        if not str(self.subject or "").strip():
            errors["subject"] = "Judul email tidak boleh kosong."

        if not str(self.body or "").strip():
            errors["body"] = "Isi email tidak boleh kosong."

        if errors:
            raise ValidationError(errors)

    # ------------------------------------------------------------------

    @classmethod
    def resolve(cls, event: str, *, company=None) -> "EmailTemplate | None":
        """
        Template yang berlaku untuk satu event.

        Baris bercompany menang; kalau tidak ada, yang global. Sengaja
        mengembalikan **None** alih-alih melempar: event yang belum
        punya template tetap harus terkirim memakai kalimat bawaan dari
        registry. Email yang tidak pernah datang tidak bisa dibedakan
        dari fitur yang belum ada.
        """
        queryset = cls.objects.filter(
            event=str(event).strip().lower(),
            is_deleted=False,
            is_active=True,
        )

        company_id = getattr(company, "pk", company)

        if company_id:
            match = queryset.filter(company_id=company_id).first()

            if match is not None:
                return match

        return queryset.filter(company__isnull=True).first()
