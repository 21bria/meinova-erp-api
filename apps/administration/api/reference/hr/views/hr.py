from apps.framework.views.reference import BaseReferenceViewSet

from apps.administration.api.reference.hr.serializers.hr import *
from apps.administration.api.reference.hr.services.hr_service import *


def reference_schema(slug):
    return {
        "endpoint": f"/api/administration/references/hr/{slug}/",
        "ui": {
            "editor": "dialog",
            "size": "md",
            "columns": 2,
        },
        "fields": {
            "code": {
                "label": "Code",
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. CODE",
                "order": 10,
            },
            "name": {
                "label": "Name",
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "Name",
                "order": 20,
            },
            "description": {
                "label": "Description",
                "form": True,
                "table": False,
                "filter": False,
                "widget": "textarea",
                "rows": 4,
                "layout": "full",
                "order": 30,
            },
            "is_active": {
                "label": "Active",
                "form": True,
                "table": True,
                "filter": True,
                "placement": "quick",
                "order": 999,
            },
        },
    }


# -----------------------------------------------------------------------------
# Personal References
# -----------------------------------------------------------------------------


class GenderViewSet(BaseReferenceViewSet):
    serializer_class = GenderSerializer
    service_class = GenderService
    framework_module = "references/hr/genders"
    schema = reference_schema("genders")


class ReligionViewSet(BaseReferenceViewSet):
    serializer_class = ReligionSerializer
    service_class = ReligionService
    framework_module = "references/hr/religions"
    schema = reference_schema("religions")


class NationalityViewSet(BaseReferenceViewSet):
    serializer_class = NationalitySerializer
    service_class = NationalityService
    framework_module = "references/hr/nationalities"
    schema = reference_schema("nationalities")


class MaritalStatusViewSet(BaseReferenceViewSet):
    serializer_class = MaritalStatusSerializer
    service_class = MaritalStatusService
    framework_module = "references/hr/marital-statuses"
    schema = reference_schema("marital-statuses")


class BloodTypeViewSet(BaseReferenceViewSet):
    serializer_class = BloodTypeSerializer
    service_class = BloodTypeService
    framework_module = "references/hr/blood-types"
    schema = reference_schema("blood-types")


# -----------------------------------------------------------------------------
# Education References
# -----------------------------------------------------------------------------


class EducationViewSet(BaseReferenceViewSet):
    serializer_class = EducationSerializer
    service_class = EducationService
    framework_module = "references/hr/educations"
    schema = reference_schema("educations")

    ordering = ["level", "sort_order", "name"]


class DegreeViewSet(BaseReferenceViewSet):
    serializer_class = DegreeSerializer
    service_class = DegreeService
    framework_module = "references/hr/degrees"
    schema = reference_schema("degrees")


class StudyFieldViewSet(BaseReferenceViewSet):
    serializer_class = StudyFieldSerializer
    service_class = StudyFieldService
    framework_module = "references/hr/study-fields"
    schema = reference_schema("study-fields")


# -----------------------------------------------------------------------------
# Employment References
# -----------------------------------------------------------------------------


class EmploymentTypeViewSet(BaseReferenceViewSet):
    serializer_class = EmploymentTypeSerializer
    service_class = EmploymentTypeService
    framework_module = "references/hr/employment-types"
    schema = reference_schema("employment-types")


class EmploymentStatusViewSet(BaseReferenceViewSet):
    serializer_class = EmploymentStatusSerializer
    service_class = EmploymentStatusService
    framework_module = "references/hr/employment-statuses"
    schema = reference_schema("employment-statuses")


class ContractTypeViewSet(BaseReferenceViewSet):
    serializer_class = ContractTypeSerializer
    service_class = ContractTypeService
    framework_module = "references/hr/contract-types"
    schema = reference_schema("contract-types")


class ProbationTypeViewSet(BaseReferenceViewSet):
    serializer_class = ProbationTypeSerializer
    service_class = ProbationTypeService
    framework_module = "references/hr/probation-types"
    schema = reference_schema("probation-types")

def employee_group_schema():
    """
    Master klasifikasi pegawai, plus **Feature Applicability**: proses
    HR mana yang berlaku untuk pegawai di group ini.

    Enam saklar, satu per proses, urut 40–90 supaya berdiri sebagai satu
    blok di bawah Description dan tidak berselang-seling dengan kolom
    referensi biasa. Bentuknya sama dengan `deducts_leave` pada Rotation
    Purpose — saklar di master, bukan cabang `if` di modul pemakainya.

    Semuanya menyala secara bawaan; yang mematikan adalah admin. Group
    yang sudah ada karena itu tidak kehilangan satu proses pun setelah
    migrasi.
    """
    schema = reference_schema("employment-groups")

    applicability = {
        "attendance_applicable": (
            "Attendance",
            "Pegawai group ini jadi subjek Attendance — jadwal, "
            "penutupan hari, dan penandaan mangkir. Matikan untuk "
            "direksi: mereka tetap Employee, cuma tidak diabsen.",
            40,
        ),
        "leave_applicable": (
            "Leave",
            "Pegawai group ini memakai proses Cuti — saldo, pengajuan, "
            "dan persetujuan.",
            50,
        ),
        "roster_applicable": (
            "Roster",
            "Ikut Roster — muncul sebagai kandidat Roster Setup dan "
            "Roster Assignment.",
            60,
        ),
        "shift_applicable": (
            "Shift",
            "Memakai Shift pada pola kerjanya. Mati = kolom Shift tidak "
            "berlaku untuk pegawai group ini.",
            70,
        ),
        "overtime_applicable": (
            "Overtime",
            "Bisa mengajukan atau dicatatkan Lembur.",
            80,
        ),
        # Dua penanda ini = penentu dokumen perjalanan (TR/BT POLICY-1).
        # Labelnya menyebut dokumennya, bukan cuma nama prosesnya: admin
        # yang membuka form ini sedang memutuskan "group ini memakai TR,
        # BT, atau keduanya", dan "Field Break" saja tidak menjawab itu.
        "field_break_applicable": (
            "Field Break / Travel Request",
            "Employees in this group may use Travel Request.",
            90,
        ),
        "business_trip_applicable": (
            "Business Trip",
            "Employees in this group may use Business Trip.",
            100,
        ),
    }

    schema["fields"] = {
        **schema["fields"],
        **{
            key: {
                "label": label,
                "form": True,
                # Enam kolom boolean di tabel referensi membuat barisnya
                # tidak terbaca lagi. Tempatnya form dan filter — yang
                # ingin tahu "siapa saja yang tidak diabsen" memakai
                # penyaring, bukan memindai enam kolom centang.
                "table": False,
                "filter": True,
                # Advanced, bukan quick. Enam dropdown boolean di toolbar
                # menutupi kotak pencarian dan tombol yang memang dipakai
                # tiap hari; generator memilih `quick` untuk boolean
                # kalau schema tidak menyebutkan apa-apa.
                "placement": "advanced",
                "help_text": help_text,
                "order": order,
            }
            for key, (label, help_text, order) in applicability.items()
        },
        # Turunan dua saklar di atas (TR/BT POLICY-1). Read-only, tampil
        # di form, bukan kolom/filter — nilainya tidak disimpan, jadi
        # tidak bisa disaring di SQL.
        #
        # `select` read-only, bukan teks: nilainya kode stabil
        # (`travel_request` / `business_trip` / `both` / `none`) dan
        # frontend menerjemahkannya lewat `codes.travel_document.*`.
        # Opsinya hanya label tampilan — tidak ada yang bisa memilihnya.
        # Hanya edit/detail: di layar create belum ada record yang bisa
        # diturunkan, dan frontend sengaja tidak menghitungnya sendiri.
        "travel_document": {
            "type": "select",
            "widget": "select",
            "label": "Travel Document",
            "read_only": True,
            "display": True,
            "table": False,
            "filter": False,
            "sortable": False,
            "options": [
                {"value": "travel_request", "label": "Travel Request"},
                {"value": "business_trip", "label": "Business Trip"},
                {"value": "both", "label": "Travel Request + Business Trip"},
                {"value": "none", "label": "No travel document enabled"},
            ],
            "modes": ["edit", "detail"],
            "help_text": (
                "Derived from Field Break / Travel Request and Business "
                "Trip after saving."
            ),
            "order": 110,
        },
        # Peringatan konfigurasi (`both` / `none`), bukan validasi:
        # tampil sebagai kotak peringatan, tidak pernah menahan simpan.
        "travel_document_warnings": {
            "widget": "warnings",
            "label": "Travel Document Warnings",
            "read_only": True,
            "display": True,
            "table": False,
            "filter": False,
            "sortable": False,
            "layout": "full",
            "modes": ["edit", "detail"],
            "order": 120,
        },
    }

    return schema


class EmployeeGroupViewSet(BaseReferenceViewSet):
    # Slug-nya `employment-groups`, sama dengan rutenya di `urls.py` dan
    # sama dengan modul FE yang sudah ada. Sempat tertulis
    # `employee-groups` di dua tempat ini saja — `endpoint` pada schema
    # jadi menunjuk URL yang tidak pernah ada, dan modul hasil generate
    # berikutnya akan menembak 404 tanpa satu pun pesan.
    serializer_class = EmployeeGroupSerializer
    service_class = EmployeeGroupService
    framework_module = "references/hr/employment-groups"
    schema = employee_group_schema()


class JobCategoryViewSet(BaseReferenceViewSet):
    serializer_class = JobCategorySerializer
    service_class = JobCategoryService
    framework_module = "references/hr/job-categories"
    schema = reference_schema("job-categories")


class JobFamilyViewSet(BaseReferenceViewSet):
    serializer_class = JobFamilySerializer
    service_class = JobFamilyService
    framework_module = "references/hr/job-families"
    schema = reference_schema("job-families")


class JobLevelViewSet(BaseReferenceViewSet):
    serializer_class = JobLevelSerializer
    service_class = JobLevelService
    framework_module = "references/hr/job-levels"
    schema = reference_schema("job-levels")


class JobGradeViewSet(BaseReferenceViewSet):
    serializer_class = JobGradeSerializer
    service_class = JobGradeService
    framework_module = "references/hr/job-grades"
    schema = reference_schema("job-grades")


# -----------------------------------------------------------------------------
# Leave References
# -----------------------------------------------------------------------------


class LeaveTypeViewSet(BaseReferenceViewSet):
    serializer_class = LeaveTypeSerializer
    service_class = LeaveTypeService
    framework_module = "references/hr/leave-types"
    schema = reference_schema("leave-types")


def rotation_purpose_schema():
    """
    Master alasan blok off roster, plus dua kolom yang membuatnya berbeda
    dari referensi biasa: penanda pemotong saldo dan saldo mana yang
    dipotong.
    """
    schema = reference_schema("rotation-purposes")

    schema["fields"] = {
        **schema["fields"],

        "deducts_leave": {
            "label": "Deducts Leave",
            "form": True,
            "table": True,
            "filter": True,
            "help_text": (
                "Blok off dengan alasan ini memotong saldo cuti. "
                "Field Break tidak; Cuti Tahunan ya."
            ),
            "order": 40,
        },

        "leave_type": {
            "label": "Leave Type",
            "form": True,
            "table": True,
            "filter": True,
            "widget": "lookup",
            "type": "lookup",
            "lookup_endpoint": (
                "/api/administration/references/hr/lookup/leave-types/"
            ),
            "display_key": "leave_type_name",
            "help_text": (
                "Saldo yang dipotong. Wajib diisi kalau Deducts Leave "
                "menyala — memotong saldo tanpa menyebut saldo yang mana "
                "tidak bisa dieksekusi."
            ),
            "order": 50,
        },

        "leave_type_name": {
            "table": False,
            "filter": False,
            "search": False,
            "sortable": False,
        },
    }

    return schema


class RotationPurposeViewSet(BaseReferenceViewSet):
    serializer_class = RotationPurposeSerializer
    service_class = RotationPurposeService
    framework_module = "references/hr/rotation-purposes"
    schema = rotation_purpose_schema()


class LeaveReasonViewSet(BaseReferenceViewSet):
    serializer_class = LeaveReasonSerializer
    service_class = LeaveReasonService
    framework_module = "references/hr/leave-reasons"
    schema = reference_schema("leave-reasons")


class AttendanceStatusViewSet(BaseReferenceViewSet):
    serializer_class = AttendanceStatusSerializer
    service_class = AttendanceStatusService
    framework_module = "references/hr/attendance-statuses"
    schema = reference_schema("attendance-statuses")


class OvertimeTypeViewSet(BaseReferenceViewSet):
    serializer_class = OvertimeTypeSerializer
    service_class = OvertimeTypeService
    framework_module = "references/hr/overtime-types"
    schema = reference_schema("overtime-types")


# -----------------------------------------------------------------------------
# Skills and Qualification References
# -----------------------------------------------------------------------------


class SkillViewSet(BaseReferenceViewSet):
    serializer_class = SkillSerializer
    service_class = SkillService
    framework_module = "references/hr/skills"
    schema = reference_schema("skills")


class SkillLevelViewSet(BaseReferenceViewSet):
    serializer_class = SkillLevelSerializer
    service_class = SkillLevelService
    framework_module = "references/hr/skill-levels"
    schema = reference_schema("skill-levels")


class CertificateTypeViewSet(BaseReferenceViewSet):
    serializer_class = CertificateTypeSerializer
    service_class = CertificateTypeService
    framework_module = "references/hr/certificate-types"
    schema = reference_schema("certificate-types")


class LicenseTypeViewSet(BaseReferenceViewSet):
    serializer_class = LicenseTypeSerializer
    service_class = LicenseTypeService
    framework_module = "references/hr/license-types"
    schema = reference_schema("license-types")


class DocumentTypeViewSet(BaseReferenceViewSet):
    serializer_class = DocumentTypeSerializer
    service_class = DocumentTypeService
    framework_module = "references/hr/document-types"
    schema = reference_schema("document-types")


class LanguageViewSet(BaseReferenceViewSet):
    serializer_class = LanguageSerializer
    service_class = LanguageService
    framework_module = "references/hr/languages"
    schema = reference_schema("languages")


class LanguageProficiencyViewSet(BaseReferenceViewSet):
    serializer_class = LanguageProficiencySerializer
    service_class = LanguageProficiencyService
    framework_module = "references/hr/language-proficiencies"
    schema = reference_schema("language-proficiencies")


# -----------------------------------------------------------------------------
# Family and Emergency References
# -----------------------------------------------------------------------------


class FamilyRelationshipViewSet(BaseReferenceViewSet):
    serializer_class = FamilyRelationshipSerializer
    service_class = FamilyRelationshipService
    framework_module = "references/hr/family-relationships"
    schema = reference_schema("family-relationships")


class EmergencyRelationshipViewSet(BaseReferenceViewSet):
    serializer_class = EmergencyRelationshipSerializer
    service_class = EmergencyRelationshipService
    framework_module = "references/hr/emergency-relationships"
    schema = reference_schema("emergency-relationships")


# -----------------------------------------------------------------------------
# Recruitment References
# -----------------------------------------------------------------------------


class RecruitmentSourceViewSet(BaseReferenceViewSet):
    serializer_class = RecruitmentSourceSerializer
    service_class = RecruitmentSourceService
    framework_module = "references/hr/recruitment-sources"
    schema = reference_schema("recruitment-sources")


class CandidateStatusViewSet(BaseReferenceViewSet):
    serializer_class = CandidateStatusSerializer
    service_class = CandidateStatusService
    framework_module = "references/hr/candidate-statuses"
    schema = reference_schema("candidate-statuses")


class InterviewTypeViewSet(BaseReferenceViewSet):
    serializer_class = InterviewTypeSerializer
    service_class = InterviewTypeService
    framework_module = "references/hr/interview-types"
    schema = reference_schema("interview-types")


class RejectionReasonViewSet(BaseReferenceViewSet):
    serializer_class = RejectionReasonSerializer
    service_class = RejectionReasonService
    framework_module = "references/hr/rejection-reasons"
    schema = reference_schema("rejection-reasons")


# -----------------------------------------------------------------------------
# Performance References
# -----------------------------------------------------------------------------


class KPICategoryViewSet(BaseReferenceViewSet):
    serializer_class = KPICategorySerializer
    service_class = KPICategoryService
    framework_module = "references/hr/kpi-categories"
    schema = reference_schema("kpi-categories")


class KPIPeriodViewSet(BaseReferenceViewSet):
    serializer_class = KPIPeriodSerializer
    service_class = KPIPeriodService
    framework_module = "references/hr/kpi-periods"
    schema = reference_schema("kpi-periods")


class KPIWeightTypeViewSet(BaseReferenceViewSet):
    serializer_class = KPIWeightTypeSerializer
    service_class = KPIWeightTypeService
    framework_module = "references/hr/kpi-weight-types"
    schema = reference_schema("kpi-weight-types")


class PerformanceRatingViewSet(BaseReferenceViewSet):
    serializer_class = PerformanceRatingSerializer
    service_class = PerformanceRatingService
    framework_module = "references/hr/performance-ratings"
    schema = reference_schema("performance-ratings")


class PerformanceCycleViewSet(BaseReferenceViewSet):
    serializer_class = PerformanceCycleSerializer
    service_class = PerformanceCycleService
    framework_module = "references/hr/performance-cycles"
    schema = reference_schema("performance-cycles")


class PerformanceTemplateViewSet(BaseReferenceViewSet):
    serializer_class = PerformanceTemplateSerializer
    service_class = PerformanceTemplateService
    framework_module = "references/hr/performance-templates"
    schema = reference_schema("performance-templates")


# -----------------------------------------------------------------------------
# Competency References
# -----------------------------------------------------------------------------


class CompetencyCategoryViewSet(BaseReferenceViewSet):
    serializer_class = CompetencyCategorySerializer
    service_class = CompetencyCategoryService
    framework_module = "references/hr/competency-categories"
    schema = reference_schema("competency-categories")


class CompetencyViewSet(BaseReferenceViewSet):
    serializer_class = CompetencySerializer
    service_class = CompetencyService
    framework_module = "references/hr/competencies"
    schema = reference_schema("competencies")


class CompetencyLevelViewSet(BaseReferenceViewSet):
    serializer_class = CompetencyLevelSerializer
    service_class = CompetencyLevelService
    framework_module = "references/hr/competency-levels"
    schema = reference_schema("competency-levels")


# -----------------------------------------------------------------------------
# Employee Separation References
# -----------------------------------------------------------------------------


class TerminationReasonViewSet(BaseReferenceViewSet):
    serializer_class = TerminationReasonSerializer
    service_class = TerminationReasonService
    framework_module = "references/hr/termination-reasons"
    schema = reference_schema("termination-reasons")


class ExitClearanceStatusViewSet(BaseReferenceViewSet):
    serializer_class = ExitClearanceStatusSerializer
    service_class = ExitClearanceStatusService
    framework_module = "references/hr/exit-clearance-statuses"
    schema = reference_schema("exit-clearance-statuses")

# --------------------------------------------------------------------------
# Training Category
# --------------------------------------------------------------------------

class TrainingCategoryViewSet(BaseReferenceViewSet):
    serializer_class = TrainingCategorySerializer
    service_class = TrainingCategoryService
    framework_module = "references/hr/training-category"
    schema = reference_schema("training-category")


class TrainingProviderViewSet(BaseReferenceViewSet):
    serializer_class = TrainingProviderSerializer
    service_class = TrainingProviderService
    framework_module = "references/hr/training-provider"
    schema = reference_schema("training-provider")


class TransportModeViewSet(BaseReferenceViewSet):
    serializer_class = TransportModeSerializer
    service_class = TransportModeService
    framework_module = "references/hr/transport-modes"
    schema = reference_schema("transport-modes")


class AccommodationTypeViewSet(BaseReferenceViewSet):
    serializer_class = AccommodationTypeSerializer
    service_class = AccommodationTypeService
    framework_module = "references/hr/accommodation-types"
    schema = reference_schema("accommodation-types")


# -----------------------------------------------------------------------------
# Visitor Management References
# -----------------------------------------------------------------------------


def visit_purpose_schema():
    """
    Alasan kunjungan, plus penanda apakah alasan ini wajib lewat alur
    persetujuan.

    Penandanya **belum dibaca siapa pun** — seluruh Visitor Request hari
    ini tetap melewati alurnya. Ditampilkan apa adanya beserta help
    text yang menyebutkannya, bukan disembunyikan: kolom yang ada di
    database tapi tidak ada di layar adalah cara tercepat membuat orang
    berikutnya menyangka fiturnya sudah jalan.
    """
    schema = reference_schema("visit-purposes")

    schema["fields"] = {
        **schema["fields"],

        "requires_approval": {
            "label": "Requires Approval",
            "form": True,
            "table": True,
            "filter": True,
            "help_text": (
                "Belum berpengaruh — seluruh Visitor Request tetap "
                "melewati alur persetujuan."
            ),
            "order": 40,
        },
    }

    return schema


class VisitPurposeViewSet(BaseReferenceViewSet):
    serializer_class = VisitPurposeSerializer
    service_class = VisitPurposeService
    framework_module = "references/hr/visit-purposes"
    schema = visit_purpose_schema()


class VisitTypeViewSet(BaseReferenceViewSet):
    serializer_class = VisitTypeSerializer
    service_class = VisitTypeService
    framework_module = "references/hr/visit-types"
    schema = reference_schema("visit-types")
