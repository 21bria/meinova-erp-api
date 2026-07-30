from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
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

    # Leave
    LeaveType,
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
    name = "training-category"
    model = TrainingCategory


@register_lookup
class TrainingProviderLookup(BaseHRReferenceLookup):
    name = "training-provider"
    model = TrainingProvider