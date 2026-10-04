from rest_framework import serializers

from apps.workflow.labels import WORKFLOW_STATUS_LABELS, label_for
from apps.workflow.models import WorkflowDefinition


class WorkflowDefinitionSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    branch_name = serializers.CharField(
        source="branch.name",
        read_only=True,
        default=None,
    )

    location_name = serializers.CharField(
        source="location.name",
        read_only=True,
        default=None,
    )

    employee_group_name = serializers.CharField(
        source="employee_group.name",
        read_only=True,
        default=None,
    )

    status_label = serializers.SerializerMethodField()

    def get_status_label(self, obj) -> str:
        return label_for(WORKFLOW_STATUS_LABELS, obj.status)

    # Dua angka yang paling sering ditanyakan di layar daftar: "alur
    # mana yang menang" dan "alur ini sudah ada isinya belum".
    specificity = serializers.IntegerField(read_only=True)

    step_count = serializers.SerializerMethodField()

    scope_label = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowDefinition
        fields = "__all__"

        read_only_fields = [
            "created_at",
            "created_by",
            "updated_at",
            "updated_by",
            "deleted_at",
            "deleted_by",
            "is_deleted",
            "company_name",
            "branch_name",
            "location_name",
            "employee_group_name",
            "status_label",
            "specificity",
            "step_count",
            "scope_label",
        ]

    def get_step_count(self, obj) -> int:
        # `step_count` sudah dianotasi selector daftar; dihitung ulang
        # hanya pada detail, yang memang satu baris.
        annotated = getattr(obj, "step_count", None)

        if annotated is not None:
            return annotated

        return obj.steps.filter(is_deleted=False).count()

    def get_scope_label(self, obj) -> str:
        """
        Ringkasan cakupan dalam satu kalimat.

        "All" ditulis eksplisit karena kolom kosong di layar setting
        gampang dibaca sebagai "belum diisi" padahal artinya "berlaku
        untuk semua" — jebakan yang sama dengan LeavePolicy.

        **Bahasa Inggris, seperti seluruh label yang dikirim API.**
        Sempat "Semua (global)", dan itu ikut dalam kebocoran yang
        sama dengan `labels.py`: teks sistem berbahasa Indonesia yang
        diterima pengguna English juga.

        Nilai ini **tidak diterjemahkan frontend**, dan itu disengaja:
        isinya campuran — nama perusahaan/lokasi/grup milik tenant
        yang tidak boleh disentuh terjemahan, dengan satu kalimat
        sistem hanya pada keadaan kosong. Memisahkan keduanya berarti
        mengubah bentuk field-nya, dan itu perubahan kontrak yang
        tidak dituntut tahap ini.
        """
        parts = [
            getattr(obj.company, "name", None),
            getattr(obj.branch, "name", None),
            getattr(obj.location, "name", None),
            getattr(obj.employee_group, "name", None),
        ]

        filled = [part for part in parts if part]

        return " · ".join(filled) if filled else "All (global)"
