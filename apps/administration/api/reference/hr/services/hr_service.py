from apps.administration.models.references.hr import (
    # -------------------------------------------------------------------------
    # Personal References
    # -------------------------------------------------------------------------
    Gender,
    Religion,
    Nationality,
    MaritalStatus,
    BloodType,

    # -------------------------------------------------------------------------
    # Education References
    # -------------------------------------------------------------------------
    Education,
    Degree,
    StudyField,

    # -------------------------------------------------------------------------
    # Employment References
    # -------------------------------------------------------------------------
    EmploymentType,
    EmploymentStatus,
    ContractType,
    ProbationType,
    EmployeeGroup,
    JobCategory,
    JobFamily,
    JobLevel,
    JobGrade,

    # -------------------------------------------------------------------------
    #  Leave References
    # -------------------------------------------------------------------------
    LeaveType,
    RotationPurpose,
    LeaveReason,
    AttendanceStatus,
    OvertimeType,

    # -------------------------------------------------------------------------
    # Skills & Qualification References
    # -------------------------------------------------------------------------
    Skill,
    SkillLevel,
    CertificateType,
    LicenseType,
    DocumentType,
    Language,
    LanguageProficiency,

    # -------------------------------------------------------------------------
    # Family & Emergency References
    # -------------------------------------------------------------------------
    FamilyRelationship,
    EmergencyRelationship,

    # -------------------------------------------------------------------------
    # Recruitment References
    # -------------------------------------------------------------------------
    RecruitmentSource,
    CandidateStatus,
    InterviewType,
    RejectionReason,

    # -------------------------------------------------------------------------
    # Performance References
    # -------------------------------------------------------------------------
    KPICategory,
    KPIPeriod,
    KPIWeightType,
    PerformanceRating,
    PerformanceCycle,
    PerformanceTemplate,

    # -------------------------------------------------------------------------
    # Competency References
    # -------------------------------------------------------------------------
    CompetencyCategory,
    Competency,
    CompetencyLevel,

    # -------------------------------------------------------------------------
    # Employee Separation References
    # -------------------------------------------------------------------------
    TerminationReason,
    ExitClearanceStatus,

    # --------------------------------------------------------------------------
    # Training Category
    # --------------------------------------------------------------------------
    TrainingCategory,
    TrainingProvider,

    # -------------------------------------------------------------------------
    # Site Rotation References
    # -------------------------------------------------------------------------
    TransportMode,
    AccommodationType,

)


class BaseMasterService:
    model = None

    @classmethod
    def list(cls):
        return cls.model.objects.order_by("sort_order", "name")


# -----------------------------------------------------------------------------
# Personal References
# -----------------------------------------------------------------------------


class GenderService(BaseMasterService):
    model = Gender


class ReligionService(BaseMasterService):
    model = Religion


class NationalityService(BaseMasterService):
    model = Nationality


class MaritalStatusService(BaseMasterService):
    model = MaritalStatus


class BloodTypeService(BaseMasterService):
    model = BloodType


# -----------------------------------------------------------------------------
# Education References
# -----------------------------------------------------------------------------


class EducationService(BaseMasterService):
    model = Education

    @classmethod
    def list(cls):
        return cls.model.objects.order_by("level", "sort_order", "name")


class DegreeService(BaseMasterService):
    model = Degree


class StudyFieldService(BaseMasterService):
    model = StudyField


# -----------------------------------------------------------------------------
# Employment References
# -----------------------------------------------------------------------------


class EmploymentTypeService(BaseMasterService):
    model = EmploymentType


class EmploymentStatusService(BaseMasterService):
    model = EmploymentStatus


class ContractTypeService(BaseMasterService):
    model = ContractType


class ProbationTypeService(BaseMasterService):
    model = ProbationType

class EmployeeGroupService(BaseMasterService):
    model = EmployeeGroup


class JobCategoryService(BaseMasterService):
    model = JobCategory


class JobFamilyService(BaseMasterService):
    model = JobFamily


class JobLevelService(BaseMasterService):
    model = JobLevel


class JobGradeService(BaseMasterService):
    model = JobGrade


# -----------------------------------------------------------------------------
#  Leave References
# -----------------------------------------------------------------------------


class LeaveTypeService(BaseMasterService):
    model = LeaveType


class RotationPurposeService(BaseMasterService):
    model = RotationPurpose


class LeaveReasonService(BaseMasterService):
    model = LeaveReason


class AttendanceStatusService(BaseMasterService):
    model = AttendanceStatus


class OvertimeTypeService(BaseMasterService):
    model = OvertimeType


# -----------------------------------------------------------------------------
# Skills & Qualification References
# -----------------------------------------------------------------------------


class SkillService(BaseMasterService):
    model = Skill


class SkillLevelService(BaseMasterService):
    model = SkillLevel


class CertificateTypeService(BaseMasterService):
    model = CertificateType


class LicenseTypeService(BaseMasterService):
    model = LicenseType


class DocumentTypeService(BaseMasterService):
    model = DocumentType


class LanguageService(BaseMasterService):
    model = Language


class LanguageProficiencyService(BaseMasterService):
    model = LanguageProficiency


# -----------------------------------------------------------------------------
# Family & Emergency References
# -----------------------------------------------------------------------------


class FamilyRelationshipService(BaseMasterService):
    model = FamilyRelationship


class EmergencyRelationshipService(BaseMasterService):
    model = EmergencyRelationship


# -----------------------------------------------------------------------------
# Recruitment References
# -----------------------------------------------------------------------------


class RecruitmentSourceService(BaseMasterService):
    model = RecruitmentSource


class CandidateStatusService(BaseMasterService):
    model = CandidateStatus


class InterviewTypeService(BaseMasterService):
    model = InterviewType


class RejectionReasonService(BaseMasterService):
    model = RejectionReason


# -----------------------------------------------------------------------------
# Performance References
# -----------------------------------------------------------------------------


class KPICategoryService(BaseMasterService):
    model = KPICategory


class KPIPeriodService(BaseMasterService):
    model = KPIPeriod


class KPIWeightTypeService(BaseMasterService):
    model = KPIWeightType


class PerformanceRatingService(BaseMasterService):
    model = PerformanceRating


class PerformanceCycleService(BaseMasterService):
    model = PerformanceCycle


class PerformanceTemplateService(BaseMasterService):
    model = PerformanceTemplate


# -----------------------------------------------------------------------------
# Competency References
# -----------------------------------------------------------------------------


class CompetencyCategoryService(BaseMasterService):
    model = CompetencyCategory


class CompetencyService(BaseMasterService):
    model = Competency


class CompetencyLevelService(BaseMasterService):
    model = CompetencyLevel


# -----------------------------------------------------------------------------
# Employee Separation References
# -----------------------------------------------------------------------------


class TerminationReasonService(BaseMasterService):
    model = TerminationReason


class ExitClearanceStatusService(BaseMasterService):
    model = ExitClearanceStatus


# --------------------------------------------------------------------------
# Training Category
# --------------------------------------------------------------------------

class TrainingCategoryService(BaseMasterService):
    model = TrainingCategory


class TrainingProviderService(BaseMasterService):
    model = TrainingProvider


# --------------------------------------------------------------------------
# Site Rotation
# --------------------------------------------------------------------------

class TransportModeService(BaseMasterService):
    model = TransportMode


class AccommodationTypeService(BaseMasterService):
    model = AccommodationType

# Visitor Management — master baru, berkas modelnya sendiri.
from apps.administration.models.references.visitor import (
    VisitPurpose,
    VisitType,
)


# -----------------------------------------------------------------------------
# Visitor Management
# -----------------------------------------------------------------------------

class VisitPurposeService(BaseMasterService):
    model = VisitPurpose


class VisitTypeService(BaseMasterService):
    model = VisitType
