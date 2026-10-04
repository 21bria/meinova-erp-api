"""
Pencarian alur dan CRUD-nya.

Pencocokan berjenjang lewat skor `specificity`, bukan urutan baris —
pola yang sama dengan `LeavePolicy` dan `RosterPolicy`. Alur khusus
Head Office menang atas alur global tanpa siapa pun perlu mengatur
prioritas manual.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError

from apps.core.services.master import BaseMasterService
from apps.framework.services.company_copy import CompanyCopyMixin

from apps.workflow import conditions
from apps.workflow.models import (
    WorkflowDefinition,
    WorkflowStatus,
    WorkflowStep,
)


class WorkflowDefinitionResolver:
    @staticmethod
    def match(
        *,
        module: str,
        document_type: str,
        company=None,
        branch=None,
        location=None,
        employee_group=None,
    ) -> WorkflowDefinition | None:
        """
        Alur paling cocok untuk satu dokumen.

        Kolom cakupan yang kosong pada alur berarti "berlaku untuk
        semua" — jadi yang dicari adalah alur yang setiap kolomnya
        entah cocok, entah kosong. Sengaja tidak memakai
        `company__in=[company, None]`: `IN (NULL)` tidak pernah cocok di
        SQL dan alur global-nya hilang diam-diam. Jebakan yang sama
        pernah kena di `DocumentSeries`.
        """
        candidates = (
            WorkflowDefinition.objects
            .filter(
                module=module,
                document_type=document_type,
                status=WorkflowStatus.ACTIVE,
                is_active=True,
                is_deleted=False,
            )
            .select_related("company", "branch", "location", "employee_group")
        )

        scope = {
            "company_id": getattr(company, "pk", company),
            "branch_id": getattr(branch, "pk", branch),
            "location_id": getattr(location, "pk", location),
            "employee_group_id": getattr(
                employee_group,
                "pk",
                employee_group,
            ),
        }

        matching = []

        for definition in candidates:
            fits = True

            for field_name, value in scope.items():
                required = getattr(definition, field_name)

                if required is not None and required != value:
                    fits = False

                    break

            if fits:
                matching.append(definition)

        if not matching:
            return None

        # Versi tertinggi jadi pemecah seri: dua alur dengan cakupan
        # persis sama sudah ditolak constraint, jadi yang tersisa cuma
        # beda versi.
        matching.sort(
            key=lambda item: (item.specificity, item.version, item.pk),
            reverse=True,
        )

        return matching[0]

    @staticmethod
    def scope_from_employee(employee) -> dict:
        """
        Cakupan pengaju, dibaca dari penempatan organisasinya.

        Inilah yang membuat "cuti karyawan Head Office" menemukan alur
        HO: pegawai yang `location`-nya Jakarta HO cocok dengan alur
        yang menyebut lokasi itu, pegawai site tidak.
        """
        organization = getattr(employee, "organization", None)
        employment = getattr(employee, "employment", None)

        return {
            "company": getattr(organization, "company", None),
            "branch": getattr(organization, "branch", None),
            "location": getattr(organization, "location", None),
            "employee_group": getattr(employment, "employee_group", None),
        }


class WorkflowDefinitionService(CompanyCopyMixin, BaseMasterService):
    model = WorkflowDefinition

    # `module` + `document_type` ikut jadi kunci sasaran: satu company
    # punya satu alur per jenis dokumen, bukan satu alur titik.
    copy_scope_fields = [
        "company",
        "branch",
        "location",
        "employee_group",
        "module",
        "document_type",
    ]

    copy_rule_fields = [
        "description",
        "version",
    ]

    # **Salinannya lahir sebagai draft, selalu.** Alur yang aktif
    # menentukan siapa menyetujui dokumen siapa, dan begitu ada satu
    # dokumen berjalan di atasnya keputusan itu tidak bisa ditarik lagi.
    # Approver-nya juga baru bisa dipastikan setelah seseorang membuka
    # `preview_approvers/` di perusahaan tujuan — struktur organisasinya
    # boleh saja belum punya pemegang role yang sama.
    copy_overrides = {"status": WorkflowStatus.DRAFT}

    # Step ikut, beserta rantai cadangannya. Alur enam meja yang
    # tersalin tanpa step-nya adalah kerangka kosong yang justru lebih
    # menyesatkan daripada tidak ada — ia terlihat sudah disiapkan.
    copy_children = [
        {
            "relation": "steps",
            "parent_field": "definition",
            "fields": [
                "sequence",
                "name",
                "description",
                "approver_type",
                "approver_user",
                "approver_role",
                "approver_position",
                "level",
                "approver_scope",
                "fallback_role",
                "approval_mode",
                "minimum_approvals",
                "can_reject",
                "can_return",
                "is_required",
                "condition",
            ],
            "children": [
                {
                    "relation": "fallbacks",
                    "parent_field": "step",
                    "fields": [
                        "sequence",
                        "role",
                        "approver_scope",
                    ],
                },
            ],
        },
    ]

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        return cls.normalize(data)

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        return cls.normalize(data)

    @staticmethod
    def normalize(data: dict[str, Any]) -> dict[str, Any]:
        for field_name in ("module", "document_type"):
            if data.get(field_name):
                data[field_name] = str(data[field_name]).strip().lower()

        if data.get("code"):
            data["code"] = str(data["code"]).strip().upper()

        return data

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        """
        Alur yang masih dipakai dokumen berjalan tidak boleh dihapus.

        `WorkflowInstance.definition` memang PROTECT, tapi soft delete
        tidak menyentuh database sama sekali — tanpa penjagaan di sini,
        alur hilang dari layar sementara dokumennya tetap berjalan dan
        tidak ada yang bisa menjelaskan step apa yang sedang ditunggu.
        """
        from apps.workflow.models import OPEN_STATUSES

        open_count = (
            instance.instances
            .filter(status__in=OPEN_STATUSES)
            .count()
        )

        if open_count:
            raise ValidationError(
                {
                    "code": (
                        f"Masih ada {open_count} dokumen berjalan di "
                        "alur ini. Selesaikan atau batalkan dulu."
                    ),
                },
            )

    @classmethod
    def activate(cls, *, instance, user=None):
        """
        Menyalakan alur, setelah memastikan ia punya step.

        Alur aktif tanpa step akan menerima pengajuan lalu gagal saat
        menyusun kotak tanda tangannya — dan pesan gagalnya muncul di
        layar pengaju, bukan di layar yang mengonfigurasinya.
        """
        if not instance.steps.filter(is_deleted=False, is_active=True).exists():
            raise ValidationError(
                {
                    "status": (
                        "Alur ini belum punya satu step pun. Tambahkan "
                        "dulu minimal satu tingkat persetujuan."
                    ),
                },
            )

        return cls.update(
            instance=instance,
            data={"status": WorkflowStatus.ACTIVE},
            user=user,
        )


class WorkflowStepService(BaseMasterService):
    model = WorkflowStep

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.assert_condition(data)

        return cls.apply_sequence(data)

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.assert_condition(data)

        return cls.apply_sequence(data, instance=instance)

    @staticmethod
    def assert_condition(data: dict[str, Any]) -> None:
        """
        Memvalidasi bentuk kondisi di layar tempat ia ditulis.

        Kalau tidak, salah ketik baru ketahuan berbulan-bulan kemudian
        saat ada yang bertanya kenapa dokumennya lewat begitu saja —
        `conditions.evaluate` sengaja memilih menjalankan step daripada
        menghilangkannya.
        """
        if "condition" not in data:
            return

        try:
            conditions.validate(data.get("condition"))
        except ValidationError as error:
            raise ValidationError({"condition": error.messages}) from error

    @staticmethod
    def apply_sequence(
        data: dict[str, Any],
        *,
        instance: WorkflowStep | None = None,
    ) -> dict[str, Any]:
        """Nomor urut berikutnya kalau dikosongkan."""
        if data.get("sequence"):
            return data

        if instance is not None and instance.sequence:
            data["sequence"] = instance.sequence

            return data

        definition = data.get(
            "definition",
            getattr(instance, "definition", None),
        )

        if definition is None:
            return data

        last = (
            WorkflowStep.objects
            .filter(definition=definition, is_deleted=False)
            .order_by("-sequence")
            .values_list("sequence", flat=True)
            .first()
        )

        data["sequence"] = (last or 0) + 1

        return data
