from django.db import models

from apps.core.models.base_reference import BaseReference


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


class EmployeeGroup(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_employee_group"


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

