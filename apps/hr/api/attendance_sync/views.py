from __future__ import annotations

from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from .permissions import (
    GENERIC_FAILURE,
    AttendanceAgentAuthentication,
    AttendanceAgentPermission,
)
from .serializers import (
    AttendanceSyncRequestSerializer,
)
from .services import (
    AttendanceSyncService,
)


class AttendanceSyncAPIView(
    APIView,
):
    """
    Endpoint mesin. Urutannya (SEC-ATT-SYNC-1):

        kunci device → tenant aktif → device → cakupan device
        → pegawai di tenant ini → AttendanceLog mentah (ATT-SYNC-CORR-1)
        → workdate.resolve() → AttendanceImportWriter → efek izin

    Hanya `AttendanceAgentAuthentication` — JWT manusia tidak dibaca.
    """

    authentication_classes = [
        AttendanceAgentAuthentication,
    ]

    permission_classes = [
        AttendanceAgentPermission,
    ]

    def post(
        self,
        request,
    ) -> Response:
        device = request.auth

        serializer = (
            AttendanceSyncRequestSerializer(
                data=request.data,
            )
        )

        serializer.is_valid(
            raise_exception=True,
        )

        validated_data = (
            serializer.validated_data
        )

        # Device ditentukan kredensialnya, bukan isi permintaan. Agent
        # yang menyebut device lain sedang salah konfigurasi (atau
        # mencoba menumpang) — ditolak, bukan diam-diam ditulis.
        declared = (validated_data.get("device_code") or "").strip()

        if declared and declared != device.code:
            raise PermissionDenied(GENERIC_FAILURE)

        result = (
            AttendanceSyncService.sync(
                agent_code=(
                    validated_data[
                        "agent_code"
                    ]
                ),
                device=device,
                records=(
                    validated_data[
                        "records"
                    ]
                ),
            )
        )

        device.last_sync_at = timezone.now()
        device.save(update_fields=["last_sync_at", "updated_at"])

        has_failures = (
            result[
                "failed_records"
            ] > 0
            or result[
                "unmatched_records"
            ] > 0
        )

        return Response(
            {
                "success":
                    not has_failures,

                "message": (
                    "Attendance records synchronized "
                    "with some issues."
                    if has_failures
                    else (
                        "Attendance records "
                        "synchronized successfully."
                    )
                ),

                "data":
                    result,
            },
            status=status.HTTP_200_OK,
        )
