"""
Bagian mana dari data pegawai yang **boleh dilihat siapa**.

Jangan tertukar dengan kewenangan `RoleAssignment`. Yang itu menjawab "**baris**
yang mana" — admin site cuma melihat pegawai site-nya. Yang ini menjawab
"**bagian mana** dari baris itu". Dua sumbu berbeda, dan yang kedua
selama ini tidak ada sama sekali: begitu seorang pegawai masuk cakupan
admin site, seluruh riwayatnya ikut terbaca — kenaikan gaji, demosi,
alasan pengunduran diri. Cakupan data tidak pernah dimaksudkan untuk
menjawab pertanyaan itu.

Aturannya jadi master tersendiri, **bukan** role atau permission baru,
karena Django Permission tidak mengenal "jenis riwayat": memecah izin
per model tidak akan pernah bisa membedakan riwayat gaji dari riwayat
kontrak, keduanya baris `EmployeeAction` yang sama. Pola yang sama
persis dengan `EmployeeActionPolicy`, dan alasannya juga sama.

Pencocokannya berjenjang lewat skor `specificity`, seperti `LeavePolicy`
dan `WorkflowDefinition`: kosong berarti **berlaku untuk semua**, bukan
"tidak berlaku".
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel


class EmployeeDataSubject(models.TextChoices):
    """
    Kelompok data yang bisa dibatasi.

    Dikelompokkan, bukan per jenis action satu-satu: yang memutuskan
    kerahasiaan berpikir "riwayat gaji", bukan "salary_change". Dua
    belas baris di layar setting untuk empat keputusan yang sebenarnya
    sama juga berarti dua belas kesempatan salah centang.
    """

    HISTORY_SALARY = "history_salary", "Salary History"
    HISTORY_SEPARATION = "history_separation", "Resignation & Termination History"
    HISTORY_MOVEMENT = "history_movement", "Transfer & Promotion History"
    HISTORY_CONTRACT = "history_contract", "Contract & Status History"

    # Kelompok di bawah ini menyangkut **keadaan sekarang** di kartu
    # pegawai, bukan riwayatnya. Dipisah karena keduanya memang
    # keputusan yang berbeda: menutup riwayat kenaikan gaji tidak ada
    # gunanya kalau angka gajinya sendiri terbaca di tab sebelah.
    FIELD_IDENTITY = "field_identity", "Identity Numbers (NIK, NPWP, Passport)"
    FIELD_PAYROLL = "field_payroll", "Payroll & Salary"
    FIELD_BANK = "field_bank", "Bank Accounts"
    FIELD_FAMILY = "field_family", "Family"
    FIELD_MEDICAL = "field_medical", "Medical"
    FIELD_DOCUMENT = "field_document", "Documents"


# Jenis `EmployeeAction` yang termasuk tiap kelompok.
#
# **Seluruh dua belas jenis harus terpetakan.** Jenis yang tidak masuk
# kelompok mana pun tidak bisa dibatasi sama sekali, dan kelalaian itu
# tidak berbunyi — barisnya cuma tetap terlihat oleh semua orang. Ada
# test yang menjaganya (`test_employee_data_policy.py`).
SUBJECT_ACTION_TYPES: dict[str, tuple[str, ...]] = {
    EmployeeDataSubject.HISTORY_SALARY: (
        "salary_change",
    ),
    EmployeeDataSubject.HISTORY_SEPARATION: (
        "resignation",
        "termination",
    ),
    EmployeeDataSubject.HISTORY_MOVEMENT: (
        "transfer",
        "promotion",
        "demotion",
        "position_change",
    ),
    EmployeeDataSubject.HISTORY_CONTRACT: (
        "contract_extension",
        "contract_change",
        "employment_type_change",
        "probation_change",
        "status_change",
    ),
}


# Field pada `EmployeeSerializer` yang termasuk tiap kelompok.
#
# Dipakai dua arah dan **wajib sama untuk keduanya**: menyaring payload
# serializer (kartu pegawai + kolom tabel) dan menyaring kolom export.
# Export membaca nilainya langsung dari instance, jadi menutup serializer
# saja meninggalkan CSV yang isinya utuh — dan itu jalur yang paling
# sering luput saat orang memikirkan "sembunyikan field".
SUBJECT_EMPLOYEE_FIELDS: dict[str, tuple[str, ...]] = {
    EmployeeDataSubject.FIELD_IDENTITY: (
        "nik",
        "passport_number",
        "tax_number",
    ),
    EmployeeDataSubject.FIELD_PAYROLL: (
        "payroll_group",
        "payroll_group_name",
        "salary_grade",
        "salary_grade_name",
        "salary_level",
        "salary_level_name",
        "currency",
        "currency_name",
        "payment_method",
        "tax_status",
        "tax_status_name",
        "tax_number_payroll",
        "bpjs_kesehatan_number",
        "bpjs_ketenagakerjaan_number",
        "overtime_eligible",
        "overtime_group",
        "overtime_group_name",
        "basic_salary",
        "allowance_template",
        "allowance_template_name",
        "deduction_template",
        "deduction_template_name",
        "effective_from",
        "effective_to",
        "payroll_notes",
    ),
}


def subject_for_action(action_type: str) -> str | None:
    """Kelompok yang memuat satu jenis action, atau `None`."""
    for subject, types in SUBJECT_ACTION_TYPES.items():
        if action_type in types:
            return str(subject)

    return None


class EmployeeDataPolicy(BaseModel):
    """
    Satu aturan kerahasiaan untuk satu kelompok data.
    """

    # ------------------------------------------------------------------
    # Untuk siapa
    # ------------------------------------------------------------------

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="employee_data_policies",
        help_text=(
            "Dikosongkan = berlaku untuk semua company yang tidak "
            "punya aturannya sendiri."
        ),
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="employee_data_policies",
        help_text=(
            "Dikosongkan = berlaku untuk semua lokasi. Diisi kalau "
            "site tertentu punya aturan kerahasiaannya sendiri."
        ),
    )

    employee_group = models.ForeignKey(
        "administration.EmployeeGroup",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="employee_data_policies",
        help_text="Dikosongkan = berlaku untuk semua golongan.",
    )

    # ------------------------------------------------------------------
    # Yang dilindungi
    # ------------------------------------------------------------------

    subject = models.CharField(
        max_length=40,
        choices=EmployeeDataSubject.choices,
        help_text=(
            "Kelompok data yang dibatasi baris ini. Kelompok yang "
            "tidak punya baris di sini tetap terlihat oleh siapa pun "
            "yang datanya masuk cakupannya."
        ),
    )

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")

    # ------------------------------------------------------------------
    # Siapa yang boleh melihat
    # ------------------------------------------------------------------

    allow_self = models.BooleanField(
        default=True,
        help_text=(
            "Pegawainya sendiri. Gajinya sendiri bukan rahasia darinya, "
            "jadi hampir tidak pernah ada alasan mematikannya."
        ),
    )

    allow_manager = models.BooleanField(
        default=True,
        help_text="Atasan langsung pegawai (`reports_to`).",
    )

    manager_levels = models.PositiveSmallIntegerField(
        default=1,
        help_text=(
            "Berapa tingkat garis pelaporan yang ikut boleh melihat. "
            "1 = atasan langsung saja, 2 = sampai atasannya atasan."
        ),
    )

    allow_department_head = models.BooleanField(
        default=False,
        help_text=(
            "Pemegang jabatan bertanda Manager di department pegawai "
            "itu. Perlu diketahui: kepala departemen **tidak** punya "
            "cakupan lokasi — di tenant yang satu departemennya "
            "tersebar di beberapa site, ini membuka data lintas site."
        ),
    )

    role = models.ForeignKey(
        "accounts.Role",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_data_policies",
        help_text=(
            "Role yang boleh melihat, mis. HR-MANAGER. Dikosongkan = "
            "tidak ada role yang ditambahkan di luar tiga pilihan di "
            "atas."
        ),
    )

    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Dimatikan = aturannya diabaikan, dan kelompok ini kembali "
            "terlihat oleh siapa pun yang datanya masuk cakupannya."
        ),
    )

    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Employee Data Policy"
        verbose_name_plural = "Employee Data Policies"
        ordering = ["subject", "sort_order", "code"]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_employee_data_policy_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    @property
    def specificity(self) -> int:
        """
        Seberapa khusus aturan ini. Makin tinggi makin menang.

        Bobotnya mengikuti `WorkflowDefinition` dan
        `EmployeeActionPolicy`: company mengalahkan lokasi, lokasi
        mengalahkan golongan. Dipakai supaya pilihannya tidak
        bergantung pada urutan baris di database.
        """
        return (
            (4 if self.company_id else 0)
            + (2 if self.location_id else 0)
            + (1 if self.employee_group_id else 0)
        )

    def clean(self):
        super().clean()

        errors = {}

        # Diperiksa terhadap **seluruh** kelompok, bukan hanya yang
        # memetakan jenis action. `SUBJECT_ACTION_TYPES` cuma memuat
        # empat kelompok riwayat, jadi versi sebelumnya menolak setiap
        # kelompok `field_*` — termasuk `field_payroll` dan
        # `field_medical` yang barisnya sudah diseed. Seed lolos karena
        # `objects.create()` tidak memanggil `full_clean()`; yang tidak
        # lolos adalah layar setting, yang lewat `BaseMasterService`
        # selalu memanggilnya. Akibatnya kelompok `field_*` tidak bisa
        # dibuat maupun disunting dari UI sama sekali.
        if self.subject and self.subject not in EmployeeDataSubject.values:
            errors["subject"] = f"Kelompok '{self.subject}' tidak dikenal."

        # Atasan tingkat nol berarti penanda "atasan boleh melihat"
        # menyala tapi tidak menunjuk siapa pun — dan yang mengisinya
        # mengira sudah membukanya untuk atasan.
        if self.allow_manager and not self.manager_levels:
            errors["manager_levels"] = (
                "Atasan boleh melihat, jadi tingkatnya minimal 1."
            )

        if errors:
            raise ValidationError(errors)
