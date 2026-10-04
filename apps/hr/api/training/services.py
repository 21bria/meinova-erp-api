from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError

from apps.core.services.master import BaseMasterService

from apps.hr.models import TrainingParticipant, TrainingProgram


class TrainingProgramService(BaseMasterService):
    model = TrainingProgram


class TrainingParticipantService(BaseMasterService):
    model = TrainingParticipant

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.assert_quota_available(
            program=data.get("program"),
        )

        return data

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        program = data.get("program", instance.program)

        # Kuota hanya diperiksa kalau pesertanya benar-benar berpindah
        # program; menyunting nilai/skor peserta yang sudah terdaftar
        # tidak boleh tertolak karena program sudah penuh.
        if program is not None and program.pk != instance.program_id:
            cls.assert_quota_available(program=program)

        return data

    @staticmethod
    def assert_quota_available(*, program) -> None:
        """
        Kuota ditegakkan di service, bukan di `Model.clean()`, karena
        aturannya menyangkut jumlah baris lain — bukan konsistensi satu
        record. Program tanpa kuota berarti tidak dibatasi.
        """
        if program is None or program.quota is None:
            return

        registered = (
            TrainingParticipant.objects
            .filter(
                program=program,
                is_deleted=False,
            )
            .count()
        )

        if registered >= program.quota:
            raise ValidationError(
                {
                    "program": (
                        f"Kuota program '{program.code}' sudah penuh "
                        f"({program.quota} peserta)."
                    ),
                }
            )
