"""
Bentuk permintaan tap kehadiran. Hanya bentuk — aturannya di `punch.py`.

Yang diterima hanya bukti dan permintaan. Pegawai, tanggal kerja, jam
server, dan hasil pemeriksaan (wajah/liveness/geofence/jarak) adalah
turunan server dan tidak punya kolom di sini.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from rest_framework import serializers

from apps.hr.api.attendance.punch import PUNCH_TYPES, PunchRequest
from apps.uploads.models import UploadedFile


# Presisi kolom `AttendanceLog.latitude/longitude` (decimal_places=7).
# Perangkat mengirim belasan digit; dibulatkan, bukan ditolak.
COORDINATE_STEP = Decimal("0.0000001")
ACCURACY_STEP = Decimal("0.01")
MAX_ACCURACY_METERS = Decimal("100000")


def _quantize(value: Decimal | None, step: Decimal) -> Decimal | None:
    if value is None:
        return None

    return value.quantize(step, rounding=ROUND_HALF_UP)


class AttendancePunchRequestSerializer(serializers.Serializer):
    client_punch_id = serializers.UUIDField()

    punch_type = serializers.CharField(max_length=10)

    # Disimpan sebagai keterangan di `raw_payload`. Jam yang berlaku
    # selalu jam server.
    client_timestamp = serializers.DateTimeField(required=False, allow_null=True)

    latitude = serializers.DecimalField(
        max_digits=None,
        decimal_places=None,
        min_value=Decimal("-90"),
        max_value=Decimal("90"),
        required=False,
        allow_null=True,
    )
    longitude = serializers.DecimalField(
        max_digits=None,
        decimal_places=None,
        min_value=Decimal("-180"),
        max_value=Decimal("180"),
        required=False,
        allow_null=True,
    )
    location_accuracy = serializers.DecimalField(
        max_digits=None,
        decimal_places=None,
        min_value=Decimal("0"),
        max_value=MAX_ACCURACY_METERS,
        required=False,
        allow_null=True,
    )

    # Diunggah lebih dulu lewat `/api/uploads/` (kategori
    # `attendance_selfie`), lalu ditunjuk dengan id-nya — konvensi yang
    # sama dengan lampiran Izin dan Cuti. Kepemilikannya dinilai service.
    selfie = serializers.PrimaryKeyRelatedField(
        queryset=UploadedFile.objects.active(),
        required=False,
        allow_null=True,
    )

    def validate_punch_type(self, value: str) -> str:
        normalized = (value or "").strip().lower()

        if normalized not in PUNCH_TYPES:
            raise serializers.ValidationError("Harus 'in' atau 'out'.")

        return normalized

    def validate(self, attrs):
        has_lat = attrs.get("latitude") is not None
        has_lng = attrs.get("longitude") is not None

        if has_lat != has_lng:
            raise serializers.ValidationError(
                {"latitude": ["Lintang dan bujur harus dikirim berpasangan."]},
            )

        attrs["latitude"] = _quantize(attrs.get("latitude"), COORDINATE_STEP)
        attrs["longitude"] = _quantize(attrs.get("longitude"), COORDINATE_STEP)
        attrs["location_accuracy"] = _quantize(
            attrs.get("location_accuracy"),
            ACCURACY_STEP,
        )

        return attrs

    def to_request(self) -> PunchRequest:
        data = self.validated_data

        return PunchRequest(
            client_punch_id=data["client_punch_id"],
            punch_type=data["punch_type"],
            client_timestamp=data.get("client_timestamp"),
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            accuracy_meters=data.get("location_accuracy"),
            photo=data.get("selfie"),
        )
