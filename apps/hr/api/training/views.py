from django.db.models import Count, Q

from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.hr.models import TrainingParticipant, TrainingProgram

from .schema import TRAINING_PARTICIPANT_SCHEMA, TRAINING_PROGRAM_SCHEMA
from .serializers import (
    TrainingParticipantSerializer,
    TrainingProgramSerializer,
)
from .services import TrainingParticipantService, TrainingProgramService


class TrainingProgramViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = TrainingProgramSerializer
    service_class = TrainingProgramService

    framework_module = "hr/training"
    schema = TRAINING_PROGRAM_SCHEMA

    search_fields = [
        "code",
        "name",
        "venue",
        "description",
        "provider__name",
        "training_category__name",
    ]

    filterset_fields = [
        "training_category",
        "provider",
        "company",
        "currency",
        "status",
        "is_mandatory",
        "start_date",
        "end_date",
    ]

    ordering_fields = [
        "code",
        "name",
        "start_date",
        "end_date",
        "duration_hours",
        "quota",
        "cost",
        "status",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-start_date",
        "name",
    ]

    def get_queryset(self):
        return (
            TrainingProgram.objects
            .select_related(
                "training_category",
                "provider",
                "company",
                "currency",
            )
            # Tanpa anotasi ini, kolom Participants memicu satu query
            # COUNT per baris lewat property `participant_count`.
            #
            # **Namanya wajib berbeda dari property-nya.** Anotasi
            # ditempelkan Django lewat `setattr` saat baris dirakit
            # menjadi instance, dan `participant_count` sudah dipegang
            # sebuah `@property` yang tidak punya setter — jadi
            # anotasi senama menjatuhkan seluruh endpoint dengan
            # `AttributeError: ... has no setter`.
            #
            # Gagalnya **hanya kalau ada barisnya**: selama tabel
            # program pelatihan nol baris, tidak ada instance yang
            # dirakit dan endpoint-nya balas 200 dengan daftar kosong.
            # Itu sebabnya bug ini baru muncul di menit pertama setelah
            # `seed_demo_hr_records` mengisi tabelnya, bukan saat
            # anotasinya ditulis. Serializer yang menyatukannya kembali
            # jadi `participant_count` supaya kunci payload-nya tidak
            # berubah untuk frontend.
            .annotate(
                participant_total=Count(
                    "participants",
                    filter=Q(participants__is_deleted=False),
                    distinct=True,
                ),
            )
            .filter(is_deleted=False)
        )


class TrainingParticipantViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = TrainingParticipantSerializer
    service_class = TrainingParticipantService

    framework_module = "hr/training-participants"
    schema = TRAINING_PARTICIPANT_SCHEMA

    search_fields = [
        "program__code",
        "program__name",
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "certificate_number",
        "notes",
    ]

    filterset_fields = [
        "program",
        "employee",
        "status",
        "is_passed",
    ]

    ordering_fields = [
        "program__code",
        "program__name",
        "employee__employee_number",
        "status",
        "score",
        "certificate_number",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "program__code",
        "employee__employee_number",
    ]

    def get_queryset(self):
        return (
            TrainingParticipant.objects
            .select_related(
                "program",
                "employee",
                "employee_training",
            )
            .filter(is_deleted=False)
        )
