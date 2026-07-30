from rest_framework import serializers

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
    # Training
    # --------------------------------------------------------------------------
    TrainingCategory,
    TrainingProvider,
)


# -----------------------------------------------------------------------------
# Personal References
# -----------------------------------------------------------------------------

class GenderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Gender
        fields = "__all__"


class ReligionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Religion
        fields = "__all__"


class NationalitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Nationality
        fields = "__all__"


class MaritalStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = MaritalStatus
        fields = "__all__"


class BloodTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = BloodType
        fields = "__all__"


# -----------------------------------------------------------------------------
# Education References
# -----------------------------------------------------------------------------

class EducationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Education
        fields = "__all__"


class DegreeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Degree
        fields = "__all__"


class StudyFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudyField
        fields = "__all__"


# -----------------------------------------------------------------------------
# Employment References
# -----------------------------------------------------------------------------

class EmploymentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmploymentType
        fields = "__all__"


class EmploymentStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmploymentStatus
        fields = "__all__"


class ContractTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContractType
        fields = "__all__"


class ProbationTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProbationType
        fields = "__all__"

class EmployeeGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeGroup
        fields = "__all__"


class JobCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = JobCategory
        fields = "__all__"


class JobFamilySerializer(serializers.ModelSerializer):
    class Meta:
        model = JobFamily
        fields = "__all__"


class JobLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobLevel
        fields = "__all__"


class JobGradeSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobGrade
        fields = "__all__"


# -----------------------------------------------------------------------------
#  Leave References
# -----------------------------------------------------------------------------

class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = "__all__"


class LeaveReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveReason
        fields = "__all__"


class AttendanceStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceStatus
        fields = "__all__"


class OvertimeTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = OvertimeType
        fields = "__all__"


# -----------------------------------------------------------------------------
# Skills & Qualification References
# -----------------------------------------------------------------------------

class SkillSerializer(serializers.ModelSerializer):
    class Meta:
        model = Skill
        fields = "__all__"


class SkillLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = SkillLevel
        fields = "__all__"


class CertificateTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CertificateType
        fields = "__all__"


class LicenseTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LicenseType
        fields = "__all__"

class DocumentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentType
        fields = "__all__"

class LanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Language
        fields = "__all__"


class LanguageProficiencySerializer(serializers.ModelSerializer):
    class Meta:
        model = LanguageProficiency
        fields = "__all__"


# -----------------------------------------------------------------------------
# Family & Emergency References
# -----------------------------------------------------------------------------


class FamilyRelationshipSerializer(serializers.ModelSerializer):
    class Meta:
        model = FamilyRelationship
        fields = "__all__"


class EmergencyRelationshipSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmergencyRelationship
        fields = "__all__"


# -----------------------------------------------------------------------------
# Recruitment References
# -----------------------------------------------------------------------------

class RecruitmentSourceSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecruitmentSource
        fields = "__all__"


class CandidateStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = CandidateStatus
        fields = "__all__"


class InterviewTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = InterviewType
        fields = "__all__"


class RejectionReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = RejectionReason
        fields = "__all__"


# -----------------------------------------------------------------------------
# Performance References
# -----------------------------------------------------------------------------


class KPICategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = KPICategory
        fields = "__all__"


class KPIPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = KPIPeriod
        fields = "__all__"


class KPIWeightTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = KPIWeightType
        fields = "__all__"


class PerformanceRatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = PerformanceRating
        fields = "__all__"


class PerformanceCycleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PerformanceCycle
        fields = "__all__"


class PerformanceTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = PerformanceTemplate
        fields = "__all__"


# -----------------------------------------------------------------------------
# Competency References
# -----------------------------------------------------------------------------

class CompetencyCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = CompetencyCategory
        fields = "__all__"


class CompetencySerializer(serializers.ModelSerializer):
    class Meta:
        model = Competency
        fields = "__all__"


class CompetencyLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompetencyLevel
        fields = "__all__"


# -----------------------------------------------------------------------------
# Employee Separation References
# -----------------------------------------------------------------------------


class TerminationReasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = TerminationReason
        fields = "__all__"


class ExitClearanceStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExitClearanceStatus
        fields = "__all__"

# -----------------------------------------------------------------------------
# Training
# -----------------------------------------------------------------------------

class TrainingCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainingCategory
        fields = "__all__"


class TrainingProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainingProvider
        fields = "__all__"