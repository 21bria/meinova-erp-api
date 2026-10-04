from django.db.models import Count, Q

from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.hr.models import Candidate, CandidateInterview, JobVacancy

from .scope import (
    CANDIDATE_INTERVIEW_SCOPE,
    CANDIDATE_SCOPE,
    JOB_VACANCY_SCOPE,
)

from .schema import (
    CANDIDATE_INTERVIEW_SCHEMA,
    CANDIDATE_SCHEMA,
    JOB_VACANCY_SCHEMA,
)
from .serializers import (
    CandidateInterviewSerializer,
    CandidateSerializer,
    JobVacancySerializer,
)
from .services import (
    CandidateInterviewService,
    CandidateService,
    JobVacancyService,
)


class JobVacancyViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    # Lowongan milik satu perusahaan, sering satu site. Tanpa cakupan
    # ini, dropdown dan tabelnya memperlihatkan seluruh lowongan tenant
    # — dan lewat situ pelamarnya ikut terbaca, karena `Candidate`
    # menurunkan otoritasnya dari sini.
    data_scope = JOB_VACANCY_SCOPE

    serializer_class = JobVacancySerializer
    service_class = JobVacancyService

    framework_module = "hr/recruitment"
    schema = JOB_VACANCY_SCHEMA

    search_fields = [
        "code",
        "title",
        "description",
        "requirements",
        "company__name",
        "department__name",
        "position__name",
    ]

    filterset_fields = [
        "company",
        "branch",
        "location",
        "division",
        "department",
        "position",
        "employment_type",
        "status",
        "open_date",
        "close_date",
    ]

    ordering_fields = [
        "code",
        "title",
        "open_date",
        "close_date",
        "quota",
        "status",
        "company__name",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-open_date",
        "title",
    ]

    def get_queryset(self):
        return (
            JobVacancy.objects
            .select_related(
                "company",
                "branch",
                "location",
                "division",
                "department",
                "position",
                "employment_type",
            )
            # Menghindari satu query COUNT per baris dari property
            # `candidate_count`.
            #
            # Namanya wajib berbeda dari property-nya — lihat catatan
            # panjang di `apps/hr/api/training/views.py`. Anotasi senama
            # menjatuhkan endpoint dengan `AttributeError: has no
            # setter`, dan **hanya kalau tabelnya ada isinya**: selama
            # nol baris tidak ada instance yang dirakit, jadi bug ini
            # menunggu di baris pertama yang dibuat orang.
            .annotate(
                candidate_total=Count(
                    "candidates",
                    filter=Q(candidates__is_deleted=False),
                    distinct=True,
                ),
            )
            .filter(is_deleted=False)
        )


class CandidateViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    # Data pelamar: nama, email, telepon, tanggal lahir, gaji yang
    # diharapkan, dan berkas lamarannya. Data orang yang bahkan belum
    # jadi pegawai — dan sampai Stage 3B.2 terbaca **setiap akun yang
    # login**, karena bacanya tidak dijaga izin dan barisnya tidak
    # dijaga cakupan.
    #
    # `hr.view_candidate` sudah ada dan sudah dipegang meja yang
    # memang merekrut; tidak ada izin baru yang dibuat di sini.
    require_view_permission = True

    # Cakupannya lewat lowongan yang dilamar — `Candidate` sendiri
    # tidak punya kolom organisasi. Lihat `scope.py`.
    data_scope = CANDIDATE_SCOPE

    serializer_class = CandidateSerializer
    service_class = CandidateService

    framework_module = "hr/candidates"
    schema = CANDIDATE_SCHEMA

    search_fields = [
        "candidate_number",
        "full_name",
        "email",
        "phone",
        "notes",
        "vacancy__code",
        "vacancy__title",
    ]

    filterset_fields = [
        "vacancy",
        "gender",
        "education",
        "source",
        "status",
        "currency",
        "rejection_reason",
        "hired_employee",
        "applied_date",
        "hired_date",
    ]

    ordering_fields = [
        "candidate_number",
        "full_name",
        "applied_date",
        "hired_date",
        "expected_salary",
        "email",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-applied_date",
        "full_name",
    ]

    def get_queryset(self):
        return (
            Candidate.objects
            .select_related(
                "vacancy",
                "gender",
                "education",
                "source",
                "status",
                "currency",
                "rejection_reason",
                "hired_employee",
                "resume_file",
            )
            .filter(is_deleted=False)
        )


class CandidateInterviewViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    # Catatan wawancara memuat nama dan penilaian pelamar yang sama.
    # Menjaga `Candidate` tapi membiarkan tab ini terbuka berarti tidak
    # menjaga apa pun — orangnya tetap terbaca lewat endpoint sebelah.
    require_view_permission = True

    data_scope = CANDIDATE_INTERVIEW_SCOPE

    serializer_class = CandidateInterviewSerializer
    service_class = CandidateInterviewService

    framework_module = "hr/candidate-interviews"
    schema = CANDIDATE_INTERVIEW_SCHEMA

    search_fields = [
        "candidate__candidate_number",
        "candidate__full_name",
        "interview_type__name",
        "notes",
    ]

    filterset_fields = [
        "candidate",
        "interview_type",
        "interviewer",
        "stage",
        "result",
    ]

    ordering_fields = [
        "stage",
        "scheduled_at",
        "result",
        "score",
        "candidate__candidate_number",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "candidate__candidate_number",
        "stage",
    ]

    def get_queryset(self):
        return (
            CandidateInterview.objects
            .select_related(
                "candidate",
                "interview_type",
                "interviewer",
            )
            .filter(is_deleted=False)
        )
