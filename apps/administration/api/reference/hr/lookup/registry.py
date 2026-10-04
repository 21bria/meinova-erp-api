from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.administration.models.references.hr import (
    HRFeature,
    applicability_field,
)

from apps.administration.models import (
    # Personal
    Gender,
    Religion,
    Nationality,
    MaritalStatus,
    BloodType,

    # Education
    Education,
    Degree,
    StudyField,

    # Employment
    EmploymentType,
    EmploymentStatus,
    ContractType,
    ProbationType,
    EmployeeGroup,

    # Job
    JobCategory,
    JobFamily,
    JobLevel,
    JobGrade,

    # Roster
    RosterPolicy,

    # Leave
    LeaveType,
    RotationPurpose,
    LeaveReason,
    AttendanceStatus,
    OvertimeType,

    # Skills and Qualifications
    Skill,
    SkillLevel,
    CertificateType,
    LicenseType,
    DocumentType,
    Language,
    LanguageProficiency,

    # Family and Emergency
    FamilyRelationship,
    EmergencyRelationship,

    # Recruitment
    RecruitmentSource,
    CandidateStatus,
    InterviewType,
    RejectionReason,

    # Performance
    KPICategory,
    KPIPeriod,
    KPIWeightType,
    PerformanceRating,
    PerformanceCycle,
    PerformanceTemplate,

    # Competency
    CompetencyCategory,
    Competency,
    CompetencyLevel,

    # Employee Separation
    TerminationReason,
    ExitClearanceStatus,

    # Training
    TrainingCategory,
    TrainingProvider,

    # Site Rotation
    TransportMode,
    AccommodationType,

    # Visitor Management
    VisitPurpose,
    VisitType,
)

class BaseHRReferenceLookup(BaseLookup):
    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "name",
    ]


# -----------------------------------------------------------------------------
# Personal References
# -----------------------------------------------------------------------------


@register_lookup
class GenderLookup(BaseHRReferenceLookup):
    name = "genders"
    model = Gender


@register_lookup
class ReligionLookup(BaseHRReferenceLookup):
    name = "religions"
    model = Religion


@register_lookup
class NationalityLookup(BaseHRReferenceLookup):
    name = "nationalities"
    model = Nationality

    @classmethod
    def serialize(cls, instance):
        """
        Ikut mengirim `code`.

        Dibaca `autofill` pada field Nationality di form Employee:
        nilainya disalin ke `nationality_code`, dan blok alamat wilayah
        (Province sampai Kelurahan/Desa) menyalakan dirinya dari situ —
        pembagian administratif Indonesia tidak berlaku untuk warga
        negara lain.

        Yang dikirim **kode**, bukan nama. Kodenya ISO-2 (`ID`), sama
        dengan `Country.code`, dan berconstraint unik; nama negara
        ditulis berbeda-beda ("Indonesian", "Indonesia", "WNI") dan
        pencocokan nama akan gagal tepat saat ada yang merapikan
        masternya. Pola yang sama dengan `requires_contract` pada
        `EmploymentTypeLookup`.
        """
        data = super().serialize(instance)

        data["code"] = instance.code

        return data


@register_lookup
class MaritalStatusLookup(BaseHRReferenceLookup):
    name = "marital-statuses"
    model = MaritalStatus


@register_lookup
class BloodTypeLookup(BaseHRReferenceLookup):
    name = "blood-types"
    model = BloodType

    search_fields = [
        "name",
    ]


# -----------------------------------------------------------------------------
# Education References
# -----------------------------------------------------------------------------


@register_lookup
class EducationLevelLookup(BaseHRReferenceLookup):
    name = "education-levels"
    model = Education

    ordering = [
        "level",
        "sort_order",
        "name",
    ]


@register_lookup
class DegreeLookup(BaseHRReferenceLookup):
    name = "degrees"
    model = Degree


@register_lookup
class StudyFieldLookup(BaseHRReferenceLookup):
    name = "study-fields"
    model = StudyField


# -----------------------------------------------------------------------------
# Employment References
# -----------------------------------------------------------------------------


@register_lookup
class EmploymentTypeLookup(BaseHRReferenceLookup):
    name = "employment-types"
    model = EmploymentType

    @classmethod
    def serialize(cls, instance):
        """
        Ikut mengirim `requires_contract`.

        Dibaca `autofill` pada field Employment Type di form Employee:
        nilainya disalin ke `employment_type_requires_contract`, dan
        kolom Contract Type/Start/End menyalakan dirinya dari situ.
        Tanpa ini form harus menebak dari kode master — dan tenant yang
        menamai jenis kepegawaiannya sendiri kehilangan kolom kontrak
        tanpa satu pun pesan.
        """
        data = super().serialize(instance)

        data["requires_contract"] = instance.requires_contract

        return data


@register_lookup
class EmploymentStatusLookup(BaseHRReferenceLookup):
    name = "employment-statuses"
    model = EmploymentStatus


@register_lookup
class ContractTypeLookup(BaseHRReferenceLookup):
    name = "contract-types"
    model = ContractType


@register_lookup
class ProbationTypeLookup(BaseHRReferenceLookup):
    name = "probation-types"
    model = ProbationType


@register_lookup
class EmployeeGroup(BaseHRReferenceLookup):
    name = "employee-groups"
    model = EmployeeGroup

    @classmethod
    def serialize(cls, instance):
        """
        Ikut mengirim keenam penanda Feature Applicability.

        Dibaca `autofill` pada field Employee Group di form Employee:
        nilainya disalin ke `employee_group_<x>_applicable`, dan kolom
        Shift, Roster Crew, serta Roster Policy menyalakan dirinya dari
        situ. Pola yang sama persis dengan `requires_contract` pada
        `EmploymentTypeLookup` — dan alasannya juga sama: menebak dari
        kode master (`BOARD`, `FIELD`, …) membuat tenant yang menamai
        group-nya sendiri kehilangan aturannya tanpa satu pun pesan.

        Kalau kunci ini dicabut dari sini, kolomnya berhenti bereaksi
        saat group-nya diganti dan tidak ada error apa pun.
        """
        data = super().serialize(instance)

        for feature in HRFeature:
            key = applicability_field(feature)

            data[key] = getattr(instance, key)

        return data


@register_lookup
class JobCategoryLookup(BaseHRReferenceLookup):
    name = "job-categories"
    model = JobCategory


@register_lookup
class JobFamilyLookup(BaseHRReferenceLookup):
    name = "job-families"
    model = JobFamily


@register_lookup
class JobLevelLookup(BaseHRReferenceLookup):
    name = "job-levels"
    model = JobLevel


@register_lookup
class JobGradeLookup(BaseHRReferenceLookup):
    name = "job-grades"
    model = JobGrade


# -----------------------------------------------------------------------------
# Leave References
# -----------------------------------------------------------------------------

@register_lookup
class RotationPurposeLookup(BaseHRReferenceLookup):
    name = "rotation-purposes"
    model = RotationPurpose

    @classmethod
    def apply_filters(cls, queryset, params):
        """
        `?document=travel_request` membuang alasan milik Business Trip
        (TR-CLEANUP-1). Tanpa parameter itu daftarnya utuh — jadwal
        roster memakai lookup yang sama. Penjagaannya tetap di
        `TravelRequestPurposeService`; ini cuma supaya yang pasti
        ditolak tidak ditawarkan.
        """
        queryset = super().apply_filters(queryset, params)

        if params.get("document") == "travel_request":
            queryset = queryset.exclude(
                code__in=RotationPurpose.BUSINESS_TRIP_CODES,
            )

        return queryset


@register_lookup
class LeaveTypeLookup(BaseHRReferenceLookup):
    name = "leave-types"
    model = LeaveType


@register_lookup
class LeaveReasonLookup(BaseHRReferenceLookup):
    name = "leave-reasons"
    model = LeaveReason


@register_lookup
class AttendanceStatusLookup(BaseHRReferenceLookup):
    name = "attendance-statuses"
    model = AttendanceStatus


@register_lookup
class OvertimeTypeLookup(BaseHRReferenceLookup):
    name = "overtime-types"
    model = OvertimeType


# -----------------------------------------------------------------------------
# Skills and Qualification References
# -----------------------------------------------------------------------------


@register_lookup
class SkillLookup(BaseHRReferenceLookup):
    name = "skills"
    model = Skill


@register_lookup
class SkillLevelLookup(BaseHRReferenceLookup):
    name = "skill-levels"
    model = SkillLevel


@register_lookup
class CertificateTypeLookup(BaseHRReferenceLookup):
    name = "certificate-types"
    model = CertificateType


@register_lookup
class LicenseTypeLookup(BaseHRReferenceLookup):
    name = "license-types"
    model = LicenseType

@register_lookup
class DocumentTypeLookup(BaseHRReferenceLookup):
    name = "document-types"
    model = DocumentType
    
@register_lookup
class LanguageLookup(BaseHRReferenceLookup):
    name = "languages"
    model = Language


@register_lookup
class LanguageProficiencyLookup(BaseHRReferenceLookup):
    name = "language-proficiencies"
    model = LanguageProficiency


# -----------------------------------------------------------------------------
# Family and Emergency References
# -----------------------------------------------------------------------------


@register_lookup
class FamilyRelationshipLookup(BaseHRReferenceLookup):
    name = "family-relationships"
    model = FamilyRelationship


@register_lookup
class EmergencyRelationshipLookup(BaseHRReferenceLookup):
    name = "emergency-relationships"
    model = EmergencyRelationship


# -----------------------------------------------------------------------------
# Recruitment References
# -----------------------------------------------------------------------------


@register_lookup
class RecruitmentSourceLookup(BaseHRReferenceLookup):
    name = "recruitment-sources"
    model = RecruitmentSource


@register_lookup
class CandidateStatusLookup(BaseHRReferenceLookup):
    name = "candidate-statuses"
    model = CandidateStatus


@register_lookup
class InterviewTypeLookup(BaseHRReferenceLookup):
    name = "interview-types"
    model = InterviewType


@register_lookup
class RejectionReasonLookup(BaseHRReferenceLookup):
    name = "rejection-reasons"
    model = RejectionReason


# -----------------------------------------------------------------------------
# Performance References
# -----------------------------------------------------------------------------


@register_lookup
class KPICategoryLookup(BaseHRReferenceLookup):
    name = "kpi-categories"
    model = KPICategory


@register_lookup
class KPIPeriodLookup(BaseHRReferenceLookup):
    name = "kpi-periods"
    model = KPIPeriod


@register_lookup
class KPIWeightTypeLookup(BaseHRReferenceLookup):
    name = "kpi-weight-types"
    model = KPIWeightType


@register_lookup
class PerformanceRatingLookup(BaseHRReferenceLookup):
    name = "performance-ratings"
    model = PerformanceRating


@register_lookup
class PerformanceCycleLookup(BaseHRReferenceLookup):
    name = "performance-cycles"
    model = PerformanceCycle


@register_lookup
class PerformanceTemplateLookup(BaseHRReferenceLookup):
    name = "performance-templates"
    model = PerformanceTemplate


# -----------------------------------------------------------------------------
# Competency References
# -----------------------------------------------------------------------------


@register_lookup
class CompetencyCategoryLookup(BaseHRReferenceLookup):
    name = "competency-categories"
    model = CompetencyCategory


@register_lookup
class CompetencyLookup(BaseHRReferenceLookup):
    name = "competencies"
    model = Competency


@register_lookup
class CompetencyLevelLookup(BaseHRReferenceLookup):
    name = "competency-levels"
    model = CompetencyLevel


# -----------------------------------------------------------------------------
# Employee Separation References
# -----------------------------------------------------------------------------


@register_lookup
class TerminationReasonLookup(BaseHRReferenceLookup):
    name = "termination-reasons"
    model = TerminationReason


@register_lookup
class ExitClearanceStatusLookup(BaseHRReferenceLookup):
    name = "exit-clearance-statuses"
    model = ExitClearanceStatus

# -----------------------------------------------------------------------------
# Training
# -----------------------------------------------------------------------------


@register_lookup
class TrainingCategoryLookup(BaseHRReferenceLookup):
    name = "training-categories"
    model = TrainingCategory


@register_lookup
class TrainingProviderLookup(BaseHRReferenceLookup):
    name = "training-providers"
    model = TrainingProvider


# -----------------------------------------------------------------------------
# Site Rotation References
# -----------------------------------------------------------------------------


@register_lookup
class TransportModeLookup(BaseHRReferenceLookup):
    name = "transport-modes"
    model = TransportMode


@register_lookup
class AccommodationTypeLookup(BaseHRReferenceLookup):
    name = "accommodation-types"
    model = AccommodationType


# -----------------------------------------------------------------------------
# Visitor Management References
# -----------------------------------------------------------------------------


@register_lookup
class VisitPurposeLookup(BaseHRReferenceLookup):
    name = "visit-purposes"
    model = VisitPurpose


@register_lookup
class VisitTypeLookup(BaseHRReferenceLookup):
    name = "visit-types"
    model = VisitType


@register_lookup
class RosterPolicyLookup(BaseLookup):
    """
    Pola roster yang bisa ditugaskan ke pegawai.

    **Hanya yang punya pola siklus.** Policy tanpa `cycle_work_days` /
    `cycle_off_days` tetap sah sebagai aturan site — hari perjalanan,
    tenggat pengajuan — tapi tidak bisa menghasilkan jadwal, dan
    menawarkannya di dropdown cuma menghasilkan pilihan yang gagal saat
    disimpan. `EmploymentAssignment.clean()` yang menolaknya; dropdown
    ini yang membuat penolakan itu tidak pernah perlu terjadi.
    """

    name = "roster-policies"
    model = RosterPolicy

    search_fields = ["code", "name"]
    ordering = ["company", "location", "code"]

    # Disaring dari form pegawai lewat penempatannya, supaya orang
    # Gebe tidak ditawari pola milik site lain. Parameter yang tidak
    # terdaftar di sini diabaikan diam-diam — itu penyebab klasik
    # dropdown yang "tidak mau tersaring".
    filter_fields = ["company_id", "location_id", "is_default"]

    @classmethod
    def get_queryset(cls):
        return (
            super().get_queryset()
            .select_related("company", "location")
            .filter(
                cycle_work_days__isnull=False,
                cycle_off_days__isnull=False,
            )
        )

    @classmethod
    def serialize(cls, instance):
        """
        Ikut mengirim pola dan basisnya.

        Dibaca `autofill` pada field Roster Policy di form Employee:
        memilih policy langsung memperlihatkan 42/14 dan panjang
        siklusnya, jadi yang mengisi Current Cycle Start tahu tanggal
        apa yang sedang dimintanya. Tanpa ini, angka yang menentukan
        seluruh jadwal seseorang cuma terbaca setelah dokumennya jadi.
        """
        data = super().serialize(instance)

        data.update(
            {
                "cycle_work_days": instance.cycle_work_days,
                "cycle_off_days": instance.cycle_off_days,
                "cycle_length": instance.cycle_length,
                "roster_start_basis": instance.roster_start_basis,
                "roster_start_basis_label": (
                    instance.get_roster_start_basis_display()
                ),
                "credit_enabled": instance.credit_enabled,
                "company_id": instance.company_id,
                "location_id": instance.location_id,
            },
        )

        return data
