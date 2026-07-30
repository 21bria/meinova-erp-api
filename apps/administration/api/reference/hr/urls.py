from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.administration.api.reference.hr.views.hr import *
from apps.administration.api.reference.hr.views.hr_attendance import *

router = DefaultRouter()

# -----------------------------------------------------------------------------
# Personal References
# -----------------------------------------------------------------------------

router.register("genders", GenderViewSet, basename="master-gender")
router.register("religions", ReligionViewSet, basename="master-religion")
router.register("nationalities", NationalityViewSet, basename="master-nationality")
router.register("marital-statuses", MaritalStatusViewSet, basename="master-marital-status")
router.register("blood-types", BloodTypeViewSet, basename="master-blood-type")

# -----------------------------------------------------------------------------
# Education References
# -----------------------------------------------------------------------------

router.register("educations", EducationViewSet, basename="master-education")
router.register("degrees", DegreeViewSet, basename="master-degree")
router.register("study-fields", StudyFieldViewSet, basename="master-study-field")

# -----------------------------------------------------------------------------
# Employment References
# -----------------------------------------------------------------------------

router.register("employment-types", EmploymentTypeViewSet, basename="master-employment-type")
router.register("employment-statuses", EmploymentStatusViewSet, basename="master-employment-status")
router.register("contract-types", ContractTypeViewSet, basename="master-contract-type")
router.register("probation-types", ProbationTypeViewSet, basename="master-probation-type")
router.register("employment-groups", EmployeeGroupViewSet, basename="master-employment-groups")

router.register("job-categories", JobCategoryViewSet, basename="master-job-category")
router.register("job-families", JobFamilyViewSet, basename="master-job-family")
router.register("job-levels", JobLevelViewSet, basename="master-job-level")
router.register("job-grades", JobGradeViewSet, basename="master-job-grade")

# -----------------------------------------------------------------------------
# Attendance & Leave References
# -----------------------------------------------------------------------------

router.register("shift-groups",ShiftGroupViewSet,basename="shift-group",)
router.register("shifts",ShiftViewSet,basename="shift",)
router.register("work-schedules",WorkScheduleViewSet,basename="work-schedule",)
router.register("work-schedule-days",WorkScheduleDayViewSet,basename="work-schedule-day",)

router.register("leave-types", LeaveTypeViewSet, basename="master-leave-type")
router.register("leave-reasons", LeaveReasonViewSet, basename="master-leave-reason")
router.register("attendance-statuses", AttendanceStatusViewSet, basename="master-attendance-status")
router.register("overtime-types", OvertimeTypeViewSet, basename="master-overtime-type")

# -----------------------------------------------------------------------------
# Skills & Qualification References
# -----------------------------------------------------------------------------

router.register("skills", SkillViewSet, basename="master-skill")
router.register("skill-levels", SkillLevelViewSet, basename="master-skill-level")
router.register("certificate-types", CertificateTypeViewSet, basename="master-certificate-type")
router.register("license-types", LicenseTypeViewSet, basename="master-license-type")
router.register("languages", LanguageViewSet, basename="master-language")
router.register("language-proficiencies", LanguageProficiencyViewSet, basename="master-language-proficiency")

# -----------------------------------------------------------------------------
# Family & Emergency References
# -----------------------------------------------------------------------------

router.register("family-relationships", FamilyRelationshipViewSet, basename="master-family-relationship")
router.register("emergency-relationships", EmergencyRelationshipViewSet, basename="master-emergency-relationship")

# -----------------------------------------------------------------------------
# Recruitment References
# -----------------------------------------------------------------------------

router.register("recruitment-sources", RecruitmentSourceViewSet, basename="master-recruitment-source")
router.register("candidate-statuses", CandidateStatusViewSet, basename="master-candidate-status")
router.register("interview-types", InterviewTypeViewSet, basename="master-interview-type")
router.register("rejection-reasons", RejectionReasonViewSet, basename="master-rejection-reason")

# -----------------------------------------------------------------------------
# Performance References
# -----------------------------------------------------------------------------

router.register("kpi-categories", KPICategoryViewSet, basename="master-kpi-category")
router.register("kpi-periods", KPIPeriodViewSet, basename="master-kpi-period")
router.register("kpi-weight-types", KPIWeightTypeViewSet, basename="master-kpi-weight-type")
router.register("performance-ratings", PerformanceRatingViewSet, basename="master-performance-rating")
router.register("performance-cycles", PerformanceCycleViewSet, basename="master-performance-cycle")
router.register("performance-templates", PerformanceTemplateViewSet, basename="master-performance-template")

# -----------------------------------------------------------------------------
# Competency References
# -----------------------------------------------------------------------------

router.register("competency-categories", CompetencyCategoryViewSet, basename="master-competency-category")
router.register("competencies", CompetencyViewSet, basename="master-competency")
router.register("competency-levels", CompetencyLevelViewSet, basename="master-competency-level")

# -----------------------------------------------------------------------------
# Employee Separation References
# -----------------------------------------------------------------------------

router.register("termination-reasons", TerminationReasonViewSet, basename="master-termination-reason")
router.register("exit-clearance-statuses", ExitClearanceStatusViewSet, basename="master-exit-clearance-status")


# -----------------------------------------------------------------------------
# Training
# -----------------------------------------------------------------------------

router.register("training-category", TrainingCategoryViewSet, basename="master-training-category")
router.register("training-provider", TrainingProviderViewSet, basename="master-training-provider")

urlpatterns = [
    path("lookup/",include( "apps.administration.api.reference.hr.lookup.urls" )),
    path("", include(router.urls)),
]