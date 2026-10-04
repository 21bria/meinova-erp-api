from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.base_reference import BaseReference


class DocumentCategory(models.TextChoices):
    IDENTITY = "IDENTITY", "Identity"
    FAMILY = "FAMILY", "Family"
    TAX = "TAX", "Tax"
    EDUCATION = "EDUCATION", "Education"
    EMPLOYMENT = "EMPLOYMENT", "Employment"
    LICENSE = "LICENSE", "License"
    HEALTH = "HEALTH", "Health"
    FINANCE = "FINANCE", "Finance"
    IMMIGRATION = "IMMIGRATION", "Immigration"
    OTHER = "OTHER", "Other"
    
# -----------------------------------------------------------------------------
# Personal References
# -----------------------------------------------------------------------------


class Gender(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_gender"


class Religion(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_religion"


class Nationality(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_nationality"


class MaritalStatus(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_marital_status"


class BloodType(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_blood_type"


# -----------------------------------------------------------------------------
# Education References
# -----------------------------------------------------------------------------


class Education(BaseReference):
    level = models.PositiveSmallIntegerField(default=1)

    class Meta(BaseReference.Meta):
        db_table = "master_education"
        ordering = ["level", "sort_order", "name"]


class Degree(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_degree"


class StudyField(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_study_field"


# -----------------------------------------------------------------------------
# Employment References
# -----------------------------------------------------------------------------


class EmploymentType(BaseReference):
    """
    Jenis kepegawaian: Permanent, Contract, Daily Worker, Intern, …

    `requires_contract` adalah penandanya, bukan kodenya. Form employment
    perlu tahu jenis mana yang membawa masa kontrak supaya kolom Contract
    Type/Start/End hanya muncul untuk yang memang berkontrak — dan
    menebaknya dari kode (`CONT`, `PKWT`, `KONTRAK`, …) berarti tenant
    yang menamai masternya sendiri kehilangan kolom itu tanpa pesan
    apa pun. Pola yang sama dengan `RotationPurpose.deducts_leave`.

    Konsekuensi lain yang disengaja: pegawai Permanent tidak boleh
    membawa Contract End yang masih terisi — kontrak PKWT-nya yang dulu
    itu sejarah, tempatnya di riwayat Employee Action, bukan di kolom
    current state. Itu ditegakkan `EmploymentAssignment.clean()`.
    """

    requires_contract = models.BooleanField(
        default=False,
        help_text=(
            "Jenis ini terikat masa kontrak — Contract Type, Contract "
            "Start, dan Contract End berlaku untuknya. Kosongkan untuk "
            "pegawai tetap."
        ),
    )

    class Meta(BaseReference.Meta):
        db_table = "master_employment_type"


class EmploymentStatus(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_employment_status"


class ContractType(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_contract_type"


class ProbationType(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_probation_type"


class HRFeature(models.TextChoices):
    """
    Proses HR yang boleh dinyalakan/dimatikan per Employee Group.

    Bukan daftar modul, dan bukan daftar izin. Yang dijawab di sini satu
    pertanyaan: **pegawai ini jadi subjek proses itu atau tidak.**
    Direksi tetap Employee — tetap terbit di Employee Master, Org Chart,
    Reporting Line, Headcount, dan Payroll; yang tidak berlaku baginya
    cuma proses operasional seperti absensi dan roster.

    Empat hal yang sengaja tidak dicampur, dan tercampurnya sudah pernah
    jadi sumber kebingungan:

    * **Employee Group** — klasifikasi pegawai.
    * **Feature Applicability** (berkas ini) — proses apa yang berlaku.
    * **Role** — apa yang boleh dilakukan pengguna.
    * **Organization Scope** — baris siapa yang boleh dilihat pengguna.

    Nilainya jadi nama kolom lewat `applicability_field()`, jadi
    menambah proses baru cukup menambah satu anggota di sini plus satu
    kolom `<value>_applicable` di `EmployeeGroup` — bukan cabang `if`
    baru di modul yang memakainya.
    """

    ATTENDANCE = "attendance", "Attendance"
    LEAVE = "leave", "Leave"
    ROSTER = "roster", "Roster"
    SHIFT = "shift", "Shift"
    OVERTIME = "overtime", "Overtime"
    FIELD_BREAK = "field_break", "Field Break"

    # Perjalanan dinas pegawai (Business Trip). Bukan penanda "kantor
    # pusat": group mana yang boleh mengajukannya adalah konfigurasi
    # tenant. Kontraknya `docs/claude/hr/business-trip.md` §7.4.
    BUSINESS_TRIP = "business_trip", "Business Trip"


def applicability_field(feature) -> str:
    """
    Nama kolom `EmployeeGroup` untuk satu proses.

    Satu-satunya tempat pemetaan proses → kolom ditulis. Modul pemakai
    memanggil ini, bukan mengetik `"roster_applicable"` sendiri — nama
    kolom yang disalin ke tujuh berkas adalah persis cara satu ganti
    nama meninggalkan enam pemanggil yang gagal tanpa suara.
    """
    return f"{HRFeature(feature).value}_applicable"


class EmployeeGroup(BaseReference):
    """
    Klasifikasi pegawai — dan sekaligus **satu-satunya sumber** yang
    memutuskan proses HR mana yang berlaku untuk pegawainya.

    Sebelum ini tidak ada tempat untuk menyimpan "direksi tidak absen".
    Yang tersedia cuma kodenya, jadi satu-satunya cara adalah
    `if employee.group == "BOARD"` yang tersebar di modul masing-masing:
    tenant yang menamai group-nya sendiri kehilangan aturannya, dan
    perubahan kebijakan berarti perubahan kode di tempat yang tidak
    pernah lengkap terdaftar.

    Enam kolom di bawah yang menggantikannya. **Semuanya `default=True`**
    — group yang sudah ada tidak boleh kehilangan satu proses pun begitu
    migrasinya jalan, dan "belum dikonfigurasi" harus berarti "seperti
    kemarin". Yang mematikan proses adalah admin yang memang membukanya
    dan mematikannya.
    """

    attendance_applicable = models.BooleanField(
        default=True,
        help_text=(
            "Pegawai group ini jadi subjek Attendance — jadwal, "
            "penutupan hari, dan penandaan mangkir."
        ),
    )

    leave_applicable = models.BooleanField(
        default=True,
        help_text=(
            "Pegawai group ini memakai proses Cuti — saldo, pengajuan, "
            "dan persetujuan."
        ),
    )

    roster_applicable = models.BooleanField(
        default=True,
        help_text=(
            "Pegawai group ini ikut Roster — muncul sebagai kandidat "
            "Roster Setup dan Roster Assignment."
        ),
    )

    shift_applicable = models.BooleanField(
        default=True,
        help_text=(
            "Pegawai group ini memakai Shift pada pola kerjanya."
        ),
    )

    overtime_applicable = models.BooleanField(
        default=True,
        help_text=(
            "Pegawai group ini bisa mengajukan/dicatatkan Lembur."
        ),
    )

    field_break_applicable = models.BooleanField(
        default=True,
        help_text=(
            "Pegawai group ini punya blok Field Break — kepulangan site "
            "lewat Travel Request."
        ),
    )

    # `default=True` seperti lima saudaranya: group yang sudah ada tidak
    # kehilangan apa pun begitu migrasinya jalan. Tenant yang ingin
    # perjalanan dinas hanya untuk pegawai kantor mematikannya pada
    # group site — konfigurasi, bukan kode.
    business_trip_applicable = models.BooleanField(
        default=True,
        help_text=(
            "Pegawai group ini boleh mengajukan Business Trip "
            "(perjalanan dinas)."
        ),
    )

    class Meta(BaseReference.Meta):
        db_table = "master_employee_group"

    def applies_to(self, feature) -> bool:
        """Proses ini berlaku untuk pegawai di group ini?"""
        return bool(getattr(self, applicability_field(feature)))


# -----------------------------------------------------------------------------
# Job References
# -----------------------------------------------------------------------------


class JobCategory(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_job_category"


class JobFamily(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_job_family"


class JobLevel(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_job_level"


class JobGrade(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_job_grade"


# -----------------------------------------------------------------------------
#  Leave References
# -----------------------------------------------------------------------------

class LeaveType(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_leave_type"


class LeaveReason(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_leave_reason"


class RotationPurpose(BaseReference):
    """
    Alasan satu blok off pada roster site — "Travel Purpose" di form
    Travel Request.

    Sengaja master tersendiri, bukan menumpang `LeaveType`, karena isinya
    dua jenis barang yang berbeda. "Field Break" adalah blok off rosternya
    sendiri dan tidak memotong saldo apa pun; "Cuti Tahunan" adalah cuti
    betulan yang memotong saldo. Kalau Field Break dimasukkan ke LeaveType
    dia ikut muncul di dropdown modul Cuti dan bisa dibuatkan saldo —
    persis yang tidak boleh terjadi.

    `deducts_leave` yang jadi penentu: dari situ perhitungan tahu baris
    mana yang menyentuh saldo cuti. Tanpa penanda ini, akumulasi hari
    kerja dan saldo hanya bisa menebak.
    """

    # Alasan milik dokumen Business Trip (TR-CLEANUP-1): tugas dinas
    # perusahaan bukan kepulangan site. Tidak bisa dipilih untuk baris
    # Travel Request baru/disunting dan tidak bisa diajukan, tapi
    # barisnya **tidak** dinonaktifkan — master ini juga dipakai jadwal
    # roster (`RotationPeriod.purpose`), dan TR lama yang menunjuknya
    # harus tetap terbaca. Kode, bukan kolom: tanpa migration.
    #
    # DEMOB (Demobilisasi) **bukan** anggotanya (TR-CLEANUP-2): pegawai
    # yang dilepas dari site/proyek — perpindahan roster/site, bukan
    # tugas dinas. Tetap milik Travel Request.
    BUSINESS_TRIP_CODES = frozenset({"DUTY", "TRAINING"})

    @property
    def is_business_trip_domain(self) -> bool:
        return self.code in self.BUSINESS_TRIP_CODES

    deducts_leave = models.BooleanField(
        default=False,
        help_text=(
            "Blok off dengan alasan ini memotong saldo cuti pegawai."
        ),
    )

    # Saldo mana yang dipotong. Wajib begitu `deducts_leave` menyala —
    # "memotong saldo" tanpa menyebut saldo yang mana tidak bisa
    # dieksekusi, dan kegagalannya baru ketahuan saat menghitung.
    leave_type = models.ForeignKey(
        "administration.LeaveType",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="rotation_purposes",
    )

    class Meta(BaseReference.Meta):
        db_table = "master_rotation_purpose"

    def clean(self):
        super().clean()

        if self.deducts_leave and not self.leave_type_id:
            raise ValidationError(
                {
                    "leave_type": (
                        "Leave Type wajib dipilih kalau alasan ini "
                        "memotong saldo cuti."
                    ),
                },
            )


class AttendanceStatus(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_attendance_status"


class OvertimeType(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_overtime_type"


# -----------------------------------------------------------------------------
# Skills and Qualification References
# -----------------------------------------------------------------------------


class Skill(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_skill"


class SkillLevel(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_skill_level"


class CertificateType(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_certificate_type"


class LicenseType(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_license_type"

class DocumentType(BaseReference):
    category = models.CharField(
        max_length=30,
        choices=DocumentCategory.choices,
        default=DocumentCategory.OTHER,
    )

    is_required = models.BooleanField(
        default=False,
    )

    is_expirable = models.BooleanField(
        default=False,
    )

    requires_number = models.BooleanField(
        default=False,
    )

    requires_issue_date = models.BooleanField(
        default=False,
    )

    requires_issuing_authority = models.BooleanField(
        default=False,
    )

    allow_multiple = models.BooleanField(
        default=False,
    )

    class Meta(BaseReference.Meta):
        db_table = "master_document_type"
        
class Language(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_language"


class LanguageProficiency(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_language_proficiency"


# -----------------------------------------------------------------------------
# Family and Emergency References
# -----------------------------------------------------------------------------


class FamilyRelationship(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_family_relationship"


class EmergencyRelationship(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_emergency_relationship"


# -----------------------------------------------------------------------------
# Recruitment References
# -----------------------------------------------------------------------------


class RecruitmentSource(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_recruitment_source"


class CandidateStatus(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_candidate_status"


class InterviewType(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_interview_type"


class RejectionReason(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_rejection_reason"

# -----------------------------------------------------------------------------
# Performance References
# -----------------------------------------------------------------------------


class KPICategory(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_kpi_category"


class KPIPeriod(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_kpi_period"


class KPIWeightType(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_kpi_weight_type"


class PerformanceRating(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_performance_rating"


class PerformanceCycle(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_performance_cycle"


class PerformanceTemplate(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_performance_template"


# -----------------------------------------------------------------------------
# Competency References
# -----------------------------------------------------------------------------


class CompetencyCategory(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_competency_category"


class Competency(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_competency"


class CompetencyLevel(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_competency_level"


# -----------------------------------------------------------------------------
# Employee Separation References
# -----------------------------------------------------------------------------


class TerminationReason(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_termination_reason"


class ExitClearanceStatus(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_exit_clearance_status"

# -----------------------------------------------------------------------------
# TrainingCategory
# -----------------------------------------------------------------------------

class TrainingCategory(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_training_category"

class TrainingProvider(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_training_provider"


# -----------------------------------------------------------------------------
# Site Rotation References
# -----------------------------------------------------------------------------
# Dipakai `RotationTravel` untuk mobilisasi pegawai site. Sengaja master
# referensi, bukan TextChoices: moda angkutan ke lokasi tambang sangat
# bergantung geografi klien (speedboat, ketinting, charter helikopter),
# dan menambahnya tidak boleh menunggu deploy.

class TransportMode(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_transport_mode"


class AccommodationType(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_accommodation_type"

