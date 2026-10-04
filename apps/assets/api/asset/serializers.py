from rest_framework import serializers

from apps.assets.api.capabilities import CapabilityFieldsMixin, capabilities

from apps.assets.models import (
    Asset,
    AssetCondition,
    AssetConditionLog,
    AssetCustody,
)


class AssetSerializer(CapabilityFieldsMixin, serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.name", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)
    facility_name = serializers.CharField(
        source="facility.name",
        read_only=True,
        default=None,
    )

    # Ringkasan custody yang sedang terbuka, untuk tampilan saja. Satu-
    # satunya jalan mengubahnya adalah dokumen custody (ASSET-3+).
    custody_type = serializers.CharField(
        source="current_custody.custody_type",
        read_only=True,
        default=None,
    )
    custody_employee = serializers.IntegerField(
        source="current_custody.employee_id",
        read_only=True,
        default=None,
    )
    custody_employee_name = serializers.CharField(
        source="current_custody.employee.__str__",
        read_only=True,
        default=None,
    )
    custody_department_name = serializers.CharField(
        source="current_custody.department.name",
        read_only=True,
        default=None,
    )
    custody_pic_name = serializers.CharField(
        source="current_custody.pic_employee.__str__",
        read_only=True,
        default=None,
    )
    custody_started_on = serializers.DateField(
        source="current_custody.started_on",
        read_only=True,
        default=None,
    )

    # Ringkasan siap-tampil untuk kolom "Holder" di tabel register.
    custody_holder = serializers.SerializerMethodField()

    # Custody terbuka secara terstruktur (ASSET-6) — kartu Current Custody
    # di layar detail. Dibaca dari baris `AssetCustody` yang terbuka, bukan
    # disimpulkan dari `status`. Read-only; tidak ada jalur tulis.
    current_custody_detail = serializers.SerializerMethodField()

    class Meta:
        model = Asset

        # Daftar eksplisit, bukan `"__all__"` — kolom penghapusan dan
        # kolom sistem tidak boleh bisa ditulis lewat API.
        fields = [
            "id",
            "asset_code",
            "company",
            "company_name",
            "category",
            "category_name",
            "name",
            "description",
            "manufacturer",
            "model",
            "serial_number",
            "tag_number",
            "acquisition_date",
            "acquisition_reference",
            "supplier_name",
            "warranty_until",
            "condition",
            "status",
            "location",
            "location_name",
            "facility",
            "facility_name",
            "current_custody",
            "custody_type",
            "custody_employee",
            "custody_employee_name",
            "custody_department_name",
            "custody_pic_name",
            "custody_started_on",
            "custody_holder",
            "current_custody_detail",
            "activated_at",
            "activated_by",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "asset_code",
            "status",
            "current_custody",
            "activated_at",
            "activated_by",
            "created_at",
            "updated_at",
        ]

        # Keunikan dijaga `AssetService` (pesan yang bisa dibaca) dan
        # constraint database. Validator otomatis DRF untuk constraint
        # bersyarat di sini hanya akan menebak — dan `asset_code` yang
        # read-only membuatnya salah menuntut field itu.
        validators = []

    def record_capabilities(self, asset):
        allowed = capabilities(self.context.get("view"), asset, {
            "update": "assets.change_asset",
            "destroy": "assets.delete_asset",
            "activate": "assets.change_asset",
            "record_condition": "assets.change_asset",
        })

        if allowed is None:
            return None

        draft = asset.status == "DRAFT"

        return {
            "can_edit": allowed["can_update"],
            "can_save": allowed["can_update"],
            "can_delete": draft and allowed["can_destroy"],
            "can_activate": draft and allowed["can_activate"],
            "can_record_condition": (
                asset.status == "ACTIVE" and allowed["can_record_condition"]
            ),
        }

    def get_custody_holder(self, asset) -> str | None:
        custody = asset.current_custody

        if custody is None:
            return None

        return custody_holder_label(custody)

    def get_current_custody_detail(self, asset) -> dict | None:
        custody = asset.current_custody

        if custody is None:
            return None

        from apps.assets.services.operations.history import AssetHistoryService

        # Dokumen pembuka hanya dihitung di layar detail — di daftar itu
        # satu query per baris, dan tabelnya tidak menampilkannya.
        view = self.context.get("view")
        provenance = (
            AssetHistoryService.provenance([custody])
            if getattr(view, "action", None) != "list"
            else {}
        )

        return CustodyRowSerializer(
            custody,
            context={**self.context, "provenance": provenance},
        ).data


def custody_holder_label(custody) -> str:
    """"Storage", nama pegawai, atau department (+ PIC)."""
    if custody.custody_type == "EMPLOYEE" and custody.employee_id:
        return str(custody.employee)

    if custody.custody_type == "ORGANIZATION" and custody.department_id:
        label = custody.department.name

        if custody.pic_employee_id:
            label = f"{label} (PIC: {custody.pic_employee})"

        return label

    return custody.get_custody_type_display()


class CustodyRowSerializer(serializers.ModelSerializer):
    """
    Satu periode custody — baris riwayat **dan** kartu custody saat ini.
    Konteks `provenance` (dari `AssetHistoryService.provenance`) mengisi
    dokumen pembuka/penutup.
    """

    custody_type_label = serializers.CharField(
        source="get_custody_type_display",
        read_only=True,
    )
    holder = serializers.SerializerMethodField()
    employee_name = serializers.CharField(
        source="employee.__str__",
        read_only=True,
        default=None,
    )
    department_name = serializers.CharField(
        source="department.name",
        read_only=True,
        default=None,
    )
    pic_employee_name = serializers.CharField(
        source="pic_employee.__str__",
        read_only=True,
        default=None,
    )
    location_name = serializers.CharField(source="location.name", read_only=True)
    facility_name = serializers.CharField(
        source="facility.name",
        read_only=True,
        default=None,
    )
    is_current = serializers.SerializerMethodField()
    opened_by = serializers.SerializerMethodField()
    closed_by = serializers.SerializerMethodField()

    class Meta:
        model = AssetCustody
        fields = [
            "id",
            "custody_type",
            "custody_type_label",
            "holder",
            "employee",
            "employee_name",
            "department",
            "department_name",
            "pic_employee",
            "pic_employee_name",
            "location",
            "location_name",
            "facility",
            "facility_name",
            "started_on",
            "ended_on",
            "start_condition",
            "end_condition",
            "is_current",
            "opened_by",
            "closed_by",
        ]
        read_only_fields = fields

    def get_holder(self, custody) -> str:
        return custody_holder_label(custody)

    def get_is_current(self, custody) -> bool:
        return custody.ended_on is None

    def _document(self, kind, ident):
        if not kind:
            return None

        return self.context.get("provenance", {}).get((kind, ident))

    def get_opened_by(self, custody):
        return self._document(custody.opened_by_type, custody.opened_by_id)

    def get_closed_by(self, custody):
        return self._document(custody.closed_by_type, custody.closed_by_id)


class ConditionLogSerializer(serializers.ModelSerializer):
    previous_condition_label = serializers.CharField(
        source="get_previous_condition_display",
        read_only=True,
    )
    new_condition_label = serializers.CharField(
        source="get_new_condition_display",
        read_only=True,
    )
    source_label = serializers.CharField(source="get_source_display", read_only=True)
    recorded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = AssetConditionLog
        fields = [
            "id",
            "previous_condition",
            "previous_condition_label",
            "new_condition",
            "new_condition_label",
            "source",
            "source_label",
            "effective_at",
            "recorded_by",
            "recorded_by_name",
            "note",
        ]
        read_only_fields = fields

    def get_recorded_by_name(self, log) -> str | None:
        user = log.recorded_by

        if user is None:
            return None

        full = user.get_full_name() if hasattr(user, "get_full_name") else ""

        return full or user.get_username()


class RecordConditionSerializer(serializers.Serializer):
    condition = serializers.ChoiceField(choices=AssetCondition.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="")
