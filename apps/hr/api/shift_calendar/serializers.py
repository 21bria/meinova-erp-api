"""
Serializer Shift Calendar.

Dua bentuk, dan keduanya sengaja berbeda: penugasan shift adalah
**master yang disunting** (CRUD biasa), sedangkan kalender adalah
**jawaban yang dirakit** (read-only, tidak menempel ke satu model).
Memaksakan keduanya jadi satu ModelSerializer berarti kalender
menyimpan barisnya sendiri, dan sejak itu ada dua versi kebenaran
tentang shift tanggal yang sama.
"""

from rest_framework import serializers

from apps.hr.api.constants import AUDIT_READ_ONLY_FIELDS
from apps.hr.models import EmployeeShiftAssignment


class EmployeeShiftAssignmentSerializer(serializers.ModelSerializer):
    employee_number = serializers.CharField(
        source="employee.employee_number",
        read_only=True,
    )
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    # `default=` di kelima kolom turunan ini bukan kosmetik: baris
    # Recovery / Rest tidak menunjuk shift sama sekali, dan DRF melempar
    # `AttributeError` saat menelusuri `shift.code` pada relasi kosong.
    # Tanpa ini, satu hari pemulihan membuat **seluruh** daftar
    # penugasan balas 500.
    shift_code = serializers.CharField(
        source="shift.code", read_only=True, default=None,
    )
    shift_name = serializers.CharField(
        source="shift.name", read_only=True, default=None,
    )

    shift_start_time = serializers.TimeField(
        source="shift.start_time",
        read_only=True,
        default=None,
    )
    shift_end_time = serializers.TimeField(
        source="shift.end_time",
        read_only=True,
        default=None,
    )
    crosses_midnight = serializers.BooleanField(
        source="shift.crosses_midnight",
        read_only=True,
        default=False,
    )

    layer_label = serializers.CharField(
        source="get_layer_display",
        read_only=True,
    )

    kind_label = serializers.CharField(
        source="get_kind_display",
        read_only=True,
    )

    day_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = EmployeeShiftAssignment
        fields = "__all__"
        read_only_fields = AUDIT_READ_ONLY_FIELDS


# ----------------------------------------------------------------------
# Kalender
# ----------------------------------------------------------------------


class ShiftCalendarDaySerializer(serializers.Serializer):
    """
    Kolom sel kalender — dan daftarnya **eksplisit**, jadi kunci baru di
    `ShiftCalendarService._cell()` tidak sampai ke layar sampai ia juga
    disebut di sini. Gagalnya diam: service dan test-nya hijau, payload
    endpoint-nya yang kehilangan kolom. Test API di
    `test_roster_shift_pattern.py` yang menjaganya.
    """

    date = serializers.DateField()
    weekday = serializers.IntegerField()

    rotation_state = serializers.CharField()
    rotation_state_label = serializers.CharField()

    is_scheduled = serializers.BooleanField()

    shift_id = serializers.IntegerField(allow_null=True)
    shift_code = serializers.CharField(allow_blank=True)
    shift_name = serializers.CharField(allow_blank=True)

    scheduled_start = serializers.TimeField(allow_null=True)
    scheduled_end = serializers.TimeField(allow_null=True)

    # Datetime ber-timezone: inilah angka yang dipakai perhitungan
    # keterlambatan, dan pada shift malam tanggal pulangnya memang
    # berbeda dari tanggal selnya. Dikirim utuh supaya layar tidak
    # menyusunnya sendiri dari jam + tanda "+1".
    scheduled_check_in = serializers.DateTimeField(allow_null=True)
    scheduled_check_out = serializers.DateTimeField(allow_null=True)

    crosses_midnight = serializers.BooleanField()

    # "23:00–07:00 (+1)" — dirakit backend, bukan disusun ulang layar.
    scheduled_label = serializers.CharField(allow_blank=True)

    shift_source = serializers.CharField(allow_null=True)

    # Sebutan yang dibaca orang. Nilainya di `shift_source` tetap
    # semantik; ini yang dirender. Frontend tidak boleh memetakannya
    # sendiri — dua daftar istilah untuk satu nilai selalu berakhir
    # dengan yang satu ketinggalan.
    shift_source_label = serializers.CharField(allow_blank=True)

    is_override = serializers.BooleanField()
    assignment_id = serializers.IntegerField(allow_null=True)

    # Alasan tertulis penyesuaian; kosong untuk tanggal yang mengikuti
    # roster. "Kenapa shift saya diubah" ditanyakan orangnya, dan
    # jawabannya sudah wajib diisi saat penyesuaian dibuat.
    assignment_reason = serializers.CharField(allow_blank=True)


class ShiftCalendarSerializer(serializers.Serializer):
    employee = serializers.DictField()
    range = serializers.DictField()

    is_roster = serializers.BooleanField()
    attendance_applicable = serializers.BooleanField()
    scheduled_days = serializers.IntegerField()

    # Hari kerja yang dikosongkan aturan jeda minimum antar shift.
    recovery_days = serializers.IntegerField()

    days = ShiftCalendarDaySerializer(many=True)
