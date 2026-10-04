"""
Shift efektif per tanggal: **kapan** sudah dijawab roster, **shift apa**
dijawab di sini.

Kenapa perlu tabel tersendiri
-----------------------------
Sebelum ini satu-satunya sumber jam untuk pegawai roster adalah
`EmploymentAssignment.shift` — **satu** shift permanen per orang. Itu
cukup untuk site yang crew-nya selalu masuk pagi, dan tidak cukup untuk
kenyataan yang paling lazim di tambang: satu crew yang blok kerjanya
enam minggu berpindah shift di dalam blok itu — 01–07 pagi, 08–14
malam, 15–21 siang. Menaruh shift di `RosterCrew` tidak menutupnya
(crew tetap satu shift), dan `WorkScheduleDay` juga tidak: barisnya
berbasis **hari dalam minggu**, sedangkan yang berubah adalah minggu
keberapa dalam siklus.

Dua lapis, dan pemisahannya yang membuat penyesuaian tidak merusak
rencana
--------------------------------------------------------------------
`BASELINE` adalah rencana shift yang lahir bersama roster; `OVERRIDE`
adalah penyesuaian supervisor atas rentang tanggal tertentu. Override
menang, dan **tanggal di luar rentangnya tetap memakai baseline** —
itulah sebabnya penyesuaian 10–12 Agustus tidak menghapus rencana
08–14 Agustus. Kalau keduanya disimpan di satu lapis, satu-satunya cara
menyisipkan tiga hari adalah memecah baris baseline jadi tiga, dan
rencana aslinya hilang.

Rotation tetap authoritative
----------------------------
Tabel ini **tidak pernah** menentukan seseorang bekerja atau tidak.
Yang menjawab itu `RotationPeriod` yang benar-benar ada barisnya (lihat
`apps.hr.api.attendance.schedule`). Baris di sini boleh saja membentang
melewati blok OFF — pada tanggal OFF ia tidak dibaca sama sekali, dan
itu memang yang diinginkan: rencana shift enam minggu tidak perlu
dipotong tiap kali rosternya digeser sehari.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.base import BaseModel


class ShiftAssignmentLayer(models.TextChoices):
    """
    Dua lapis, dengan `OVERRIDE` selalu menang.

    Sengaja **bukan** kolom `priority` bebas angka: prioritas bebas
    membuat "mana yang berlaku" bergantung angka yang diketik orang,
    dan dua baris berprioritas sama mengembalikan pertanyaannya ke
    awal. Dua lapis tetap bisa dijawab tanpa melihat data.
    """

    BASELINE = "baseline", "Roster Baseline"
    OVERRIDE = "override", "Adjustment"


class ShiftAssignmentKind(models.TextChoices):
    """
    Apa yang dinyatakan sebuah baris: sebuah shift, atau justru
    **tidak ada** shift.

    `REST` lahir dari aturan jeda minimum antar shift
    (`RosterPolicy.min_rest_hours`): pergantian yang tidak menyisakan
    istirahat cukup disela hari pemulihan, dan hari itu harus bisa
    dinyatakan sebagai baris — bukan sebagai baris yang hilang.

    Kenapa bukan sekadar **tidak menulis apa pun** pada tanggal itu.
    Karena "tidak ada baris" sudah punya arti lain, dan artinya
    berlawanan: resolver turun ke `EmploymentAssignment.shift` lalu
    `WorkScheduleDay`, jadi tanggal tanpa baris tetap menghasilkan shift
    permanen orangnya. Hari pemulihan yang ditulis sebagai kekosongan
    justru terbit sebagai hari kerja biasa — dan `RotationPeriod`-nya
    masih WORK, jadi penutup hari tetap menagihnya.

    Kenapa bukan sebuah baris master `Shift` bernama "Rest". Karena
    `Shift` menyimpan jam, dan hari pemulihan tidak punya jam. Shift
    tanpa jam yang harus dikenali dari kodenya adalah kode shift yang
    ditulis di kode program, dan itu persis yang tidak boleh ada di
    seluruh jalur ini.
    """

    WORK = "work", "Working Shift"
    REST = "rest", "Recovery / Rest"


class EmployeeShiftAssignment(BaseModel):
    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.CASCADE,
        related_name="shift_assignments",
    )

    # Boleh kosong, dan **hanya** untuk baris `REST`: hari pemulihan
    # tidak menunjuk shift mana pun karena ia memang tidak punya jam.
    # Yang menjaga pasangannya `clean()` di bawah.
    shift = models.ForeignKey(
        "administration.Shift",
        on_delete=models.PROTECT,
        related_name="employee_shift_assignments",
        null=True,
        blank=True,
        help_text=(
            "Jam kerjanya milik master Shift — mengubah jam di sana "
            "mengubah jendela terjadwal tanpa perubahan kode. "
            "Dikosongkan hanya untuk baris Recovery / Rest."
        ),
    )

    kind = models.CharField(
        max_length=20,
        choices=ShiftAssignmentKind.choices,
        default=ShiftAssignmentKind.WORK,
        db_index=True,
        help_text=(
            "Working Shift = baris ini menetapkan shift. "
            "Recovery / Rest = baris ini justru menyatakan tidak ada "
            "shift, dan tanggalnya tidak menerbitkan kewajiban presensi."
        ),
    )

    layer = models.CharField(
        max_length=20,
        choices=ShiftAssignmentLayer.choices,
        default=ShiftAssignmentLayer.BASELINE,
        db_index=True,
        help_text=(
            "Baseline = rencana shift blok kerja. Adjustment = "
            "penyesuaian yang menang atas baseline pada rentangnya."
        ),
    )

    # Inklusif di kedua ujung, dan **wajib** dua-duanya. Rentang terbuka
    # ("mulai 8 Agustus, sampai kapan pun") terlihat praktis sampai ada
    # baris kedua: dua rentang terbuka pada satu lapis tidak punya
    # jawaban yang bisa ditebak, dan menutupnya diam-diam saat baris
    # baru masuk berarti sistem mengubah rencana yang tidak diminta
    # siapa pun.
    start_date = models.DateField()
    end_date = models.DateField()

    reason = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="Kenapa shift-nya berbeda. Wajib untuk Adjustment.",
    )

    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "hr_employee_shift_assignment"

        ordering = ["employee", "start_date", "layer"]

        indexes = [
            models.Index(
                fields=["employee", "start_date", "end_date"],
                name="idx_shift_assignment_emp_range",
            ),
        ]

    def __str__(self):
        return (
            f"{self.employee_id} {self.start_date}..{self.end_date} "
            f"{self.get_layer_display()}"
        )

    @property
    def is_rest(self) -> bool:
        return self.kind == ShiftAssignmentKind.REST

    @property
    def day_count(self) -> int | None:
        if not self.start_date or not self.end_date:
            return None

        return (self.end_date - self.start_date).days + 1

    def clean(self):
        super().clean()

        errors = {}

        if self.start_date and self.end_date:
            if self.end_date < self.start_date:
                errors["end_date"] = (
                    "End date tidak boleh sebelum start date."
                )

        # Pasangan `kind` × `shift`, dan diperiksa dua arah. Baris kerja
        # tanpa shift tidak punya jam sama sekali; baris pemulihan yang
        # menunjuk shift punya dua jawaban untuk tanggal yang sama —
        # "tidak bekerja" dan "bekerja jam sekian" — dan yang kedua
        # cepat atau lambat menang di salah satu pembaca.
        if self.kind == ShiftAssignmentKind.REST:
            if self.shift_id:
                errors["shift"] = (
                    "Baris Recovery / Rest tidak menunjuk shift: hari "
                    "pemulihan memang tidak punya jam kerja."
                )
        elif not self.shift_id:
            errors["shift"] = "Shift wajib diisi."

        if (
            self.layer == ShiftAssignmentLayer.OVERRIDE
            and not (self.reason or "").strip()
        ):
            # Penyesuaian tanpa alasan tertulis tidak bisa diaudit —
            # dan "kenapa shift saya diubah" adalah pertanyaan yang
            # pasti ditanyakan orangnya.
            errors["reason"] = (
                "Adjustment wajib menyebutkan alasannya."
            )

        # Tumpang tindih **di dalam lapis yang sama** membuat "shift apa
        # yang berlaku" punya dua jawaban. Antar lapis justru mekanisme
        # yang diinginkan, jadi yang diperiksa hanya sesama lapis.
        if (
            self.employee_id
            and self.start_date
            and self.end_date
            and not errors
        ):
            clash = (
                EmployeeShiftAssignment.objects
                .filter(
                    employee_id=self.employee_id,
                    layer=self.layer,
                    is_deleted=False,
                    start_date__lte=self.end_date,
                    end_date__gte=self.start_date,
                )
                .exclude(pk=self.pk)
                .order_by("start_date")
                .first()
            )

            if clash is not None:
                errors["start_date"] = (
                    "Rentang ini bertabrakan dengan penugasan shift "
                    f"{clash.start_date:%d %b %Y}–"
                    f"{clash.end_date:%d %b %Y} pada lapis yang sama."
                )

        if errors:
            raise ValidationError(errors)


# Urutan wewenang, dan dibaca dari kiri: baris `OVERRIDE` yang memuat
# tanggalnya menang atas `BASELINE`. Dipakai resolver di
# `apps.hr.api.attendance.schedule`.
LAYER_PRECEDENCE = [
    ShiftAssignmentLayer.OVERRIDE,
    ShiftAssignmentLayer.BASELINE,
]


def assignment_lookup(employee_ids, start, end):
    """
    Baris aktif yang menyentuh rentang, untuk sekumpulan pegawai.

    Satu-satunya tempat penyaringan ditulis — jalur satu pegawai,
    kalender, dan importer sama-sama lewat sini.
    """
    return (
        EmployeeShiftAssignment.objects
        .filter(
            employee_id__in=list(employee_ids),
            is_deleted=False,
            is_active=True,
            start_date__lte=end,
            end_date__gte=start,
        )
        .select_related("shift")
        .order_by("start_date")
    )
