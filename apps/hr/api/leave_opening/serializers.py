from rest_framework import serializers

from apps.hr.api.constants import AUDIT_READ_ONLY_FIELDS
from apps.hr.api.leave.eligibility import (
    LeaveEligibilityResolver,
    OpeningValidation,
)
from apps.hr.models import LeaveOpeningBalance


class LeaveOpeningBalanceSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    employee_number = serializers.CharField(
        source="employee.employee_number",
        read_only=True,
    )

    leave_type_name = serializers.CharField(
        source="leave_type.name",
        read_only=True,
        default=None,
    )

    source_label = serializers.CharField(
        source="get_source_display",
        read_only=True,
    )

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    # Lima kolom kelayakan, **diturunkan saat dibaca** dan bukan
    # disimpan. Alasannya keras: Join Date dan Leave Policy dua-duanya
    # bisa dibetulkan setelah filenya diimport, dan justru itu yang
    # dilakukan HR terhadap baris yang ditandai REVIEW. Penilaian yang
    # dibekukan saat import akan tetap berbunyi REVIEW sesudah sebabnya
    # dibereskan — dan sesudah itu tidak ada yang mempercayainya lagi.
    #
    # Yang **dibekukan** cuma angkanya sendiri (`days`) dan tanggal
    # hangusnya; keduanya hak, bukan penilaian.
    join_date = serializers.SerializerMethodField()

    eligible_date = serializers.SerializerMethodField()

    validation = serializers.SerializerMethodField()

    validation_label = serializers.SerializerMethodField()

    validation_reason = serializers.SerializerMethodField()

    # Keduanya diisi service dari tanggal berlaku dan policy, jadi
    # boleh dikosongkan di form. `required=False` saja tidak cukup
    # untuk `year`: kolomnya wajib di model, dan DRF akan menolak
    # request sebelum service sempat menurunkannya.
    year = serializers.IntegerField(required=False)

    expires_at = serializers.DateField(
        required=False,
        allow_null=True,
    )

    # Boleh dikosongkan: diisi service dari tanggal go-live perusahaan
    # pegawainya. Kolomnya wajib di model, jadi `required=False` di sini
    # adalah satu-satunya cara jalur itu sempat jalan — DRF menolak
    # request lebih dulu kalau tidak. Jebakan yang sama dengan `year` di
    # atas dan `location` di Roster Setup.
    opening_date = serializers.DateField(required=False)

    class Meta:
        model = LeaveOpeningBalance
        fields = "__all__"

        # `UniqueTogetherValidator` yang dibangkitkan DRF dari
        # constraint (employee, leave_type) dimatikan, dan itu bukan
        # melonggarkan penjagaan — constraint database tetap berlaku,
        # dan `validate()` di bawah memeriksa hal yang sama dengan
        # pesan yang menyebut dokumen bentroknya.
        #
        # Dua alasan mematikannya. Pesannya sendiri ("The fields
        # employee, leave_type must make a unique set") tidak menyebut
        # siapa pemakainya, jadi tidak bisa ditindaklanjuti pengetiknya.
        # Dan validator itu **menuntut seluruh anggota constraint hadir
        # di payload**: PATCH yang cuma mengubah `days` akan dibalas
        # "This field is required" untuk kolom yang tidak disentuh
        # siapa pun. Jebakan yang sama dengan `sequence` di
        # RotationPeriod dan TravelArrangement.
        validators = []

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "employee_name",
            "employee_number",
            "leave_type_name",
            "source_label",
            "status_label",
            "join_date",
            "eligible_date",
            "validation",
            "validation_label",
            "validation_reason",
            # Ketiganya cuma berpindah lewat tombol Post/Unpost.
            # Membiarkannya bisa ditulis lewat form berarti sebuah baris
            # bisa dinyatakan berlaku tanpa `sync_balance` pernah jalan
            # — statusnya "posted", kartu saldonya tetap nol, dan tidak
            # ada satu pun pesan yang menyebutkannya.
            "status",
            "posted_at",
            "posted_by",
        ]

    # ------------------------------------------------------------------
    # Kelayakan
    # ------------------------------------------------------------------

    def _assessment(self, instance) -> dict:
        """
        Satu perhitungan per baris, dipakai lima field di atas.

        Resolver-nya disimpan di `context` supaya seluruh baris dalam
        satu halaman memakai memo yang sama — daftar 20 baris milik satu
        perusahaan lazimnya cuma butuh satu query policy, bukan dua
        puluh. `many=True` membagikan context yang sama ke tiap child,
        jadi ini benar-benar satu instance per request.
        """
        cached = getattr(instance, "_opening_assessment", None)

        if cached is not None:
            return cached

        context = self.context

        resolver = context.get("leave_eligibility_resolver")

        if resolver is None:
            resolver = LeaveEligibilityResolver()

            # Serializer yang dipakai tanpa context (mis. di test) tetap
            # bekerja — cuma tanpa memo antar baris.
            if isinstance(context, dict):
                context["leave_eligibility_resolver"] = resolver

        eligibility = resolver.for_employee(
            instance.employee,
            instance.leave_type,
        )

        status, reason = resolver.classify(
            days=instance.days,
            eligibility=eligibility,
            opening_date=instance.opening_date,
        )

        assessment = {
            "join_date": eligibility.join_date,
            "eligible_date": eligibility.eligible_date,
            "validation": status,
            "validation_label": OpeningValidation.label(status),
            "validation_reason": reason,
        }

        instance._opening_assessment = assessment

        return assessment

    def get_join_date(self, obj):
        return self._assessment(obj)["join_date"]

    def get_eligible_date(self, obj):
        return self._assessment(obj)["eligible_date"]

    def get_validation(self, obj):
        return self._assessment(obj)["validation"]

    def get_validation_label(self, obj):
        return self._assessment(obj)["validation_label"]

    def get_validation_reason(self, obj):
        return self._assessment(obj)["validation_reason"]

    def validate(self, attrs):
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        errors = {}

        employee = resolved("employee")
        leave_type = resolved("leave_type")

        # Duplikat ditolak di sini, bukan dibiarkan jatuh sebagai
        # IntegrityError dari constraint: pesan constraint tidak
        # menempel di kolom mana pun dan tidak menyebut dokumen yang
        # bentrok, padahal itu satu-satunya hal yang bisa
        # ditindaklanjuti pengetiknya.
        if employee and leave_type:
            existing = (
                LeaveOpeningBalance.objects
                .filter(
                    employee=employee,
                    leave_type=leave_type,
                    is_deleted=False,
                )
                .exclude(pk=getattr(instance, "pk", None))
                .first()
            )

            if existing is not None:
                errors["leave_type"] = (
                    f"{employee.employee_number} sudah punya saldo awal "
                    f"{existing.days} hari untuk jenis cuti ini "
                    f"(berlaku {existing.opening_date}). Saldo awal "
                    f"hanya untuk migrasi — koreksi sesudahnya lewat "
                    f"Adjustment di kartu saldo."
                )

        days = resolved("days")

        if days is not None and days < 0:
            errors["days"] = (
                "Saldo awal tidak boleh negatif. Untuk koreksi "
                "pengurangan, pakai Adjustment di kartu saldo."
            )

        year = resolved("year")

        if year is not None and not (2000 <= year <= 2100):
            errors["year"] = "Tahun harus di antara 2000 dan 2100."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
