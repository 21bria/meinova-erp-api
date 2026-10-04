"""
Memindahkan data engine approval lama (`apps.framework.approval`) ke
engine baru.

Dijalankan otomatis per schema tenant, bukan lewat management command,
supaya tidak ada tenant yang ketinggalan lalu kehilangan pengajuan yang
sedang berjalan begitu model lamanya dihapus di migration berikutnya.

Aman dijalankan di tenant yang tabel lamanya kosong — dan aman diulang:
alur yang sudah punya padanannya di engine baru dilewati, bukan
digandakan.
"""

from django.db import migrations


# Pemetaan sumber approver. Nilai kirinya `ApproverSource` lama, kanan
# `ApproverType` baru. Namanya berbeda karena engine baru memakai
# kosakata yang sama dengan layar setting-nya.
SOURCE_MAP = {
    "reports_to": "manager",
    "position": "position",
    "department_manager": "department_head",
    "role": "role",
}

INSTANCE_STATUS_MAP = {
    "draft": "draft",
    "pending": "pending",
    "approved": "approved",
    "rejected": "rejected",
    "cancelled": "cancelled",
}

APPROVAL_STATUS_MAP = {
    "pending": "pending",
    "approved": "approved",
    "rejected": "rejected",
    "skipped": "skipped",
}


def _unique_code(WorkflowDefinition, flow) -> str:
    """
    Kode alur yang belum terpakai.

    Engine lama tidak mengunci `code` (keunikannya di kombinasi
    company + module + document_type), jadi tenant lama lazim punya
    beberapa alur bernama sama — di demo, `TR-DEFAULT` dipakai dua kali
    untuk `site_rotation` dan `travel_request`. Engine baru mengunci
    kodenya, jadi yang bentrok diberi akhiran jenis dokumennya, bukan
    ditolak — migration yang gagal separuh jalan meninggalkan tenant
    tanpa alur sama sekali.
    """
    base = (flow.code or f"{flow.module}-{flow.document_type}").upper()

    if not WorkflowDefinition.objects.filter(code=base).exists():
        return base

    suffixed = f"{base}-{flow.document_type.upper()}"[:100]

    if not WorkflowDefinition.objects.filter(code=suffixed).exists():
        return suffixed

    return f"{suffixed}-{flow.pk}"[:100]


def forwards(apps, schema_editor):
    ApprovalFlow = apps.get_model("framework", "ApprovalFlow")
    ApprovalRequest = apps.get_model("framework", "ApprovalRequest")

    WorkflowDefinition = apps.get_model("workflow", "WorkflowDefinition")
    WorkflowStep = apps.get_model("workflow", "WorkflowStep")
    WorkflowInstance = apps.get_model("workflow", "WorkflowInstance")
    WorkflowApproval = apps.get_model("workflow", "WorkflowApproval")

    step_map: dict[int, object] = {}

    for flow in ApprovalFlow.objects.filter(is_deleted=False):
        definition, _ = WorkflowDefinition.objects.get_or_create(
            module=flow.module,
            document_type=flow.document_type,
            company_id=flow.company_id,
            branch_id=None,
            location_id=None,
            employee_group_id=None,
            version=1,
            defaults={
                "code": _unique_code(WorkflowDefinition, flow),
                "name": flow.name,
                "description": flow.description,
                # Alur lama yang aktif memang sedang dipakai produksi —
                # menerbitkannya sebagai Draft akan membuat setiap
                # pengajuan besok pagi gagal mencari alurnya.
                "status": "active" if flow.is_active else "inactive",
                "is_active": flow.is_active,
                "is_deleted": False,
            },
        )

        for old_step in flow.steps.filter(is_deleted=False).order_by(
            "sequence",
        ):
            step, _ = WorkflowStep.objects.get_or_create(
                definition=definition,
                sequence=old_step.sequence,
                defaults={
                    "name": old_step.name,
                    "approver_type": SOURCE_MAP.get(
                        old_step.source,
                        "manager",
                    ),
                    "approver_role_id": old_step.role_id,
                    "fallback_role_id": old_step.fallback_role_id,
                    "level": old_step.level,
                    "approval_mode": "any",
                    "minimum_approvals": 1,
                    # `is_optional` lama adalah kebalikan `is_required`
                    # baru. Membalik tandanya penting: step opsional
                    # yang ikut jadi wajib akan menggagalkan pengajuan
                    # di tenant yang struktur organisasinya belum
                    # lengkap.
                    "is_required": not old_step.is_optional,
                    "is_active": old_step.is_active,
                    "is_deleted": False,
                },
            )

            step_map[old_step.pk] = step

    for request in ApprovalRequest.objects.filter(
        is_deleted=False,
    ).select_related("flow"):
        flow = request.flow

        definition = WorkflowDefinition.objects.filter(
            module=flow.module,
            document_type=flow.document_type,
            company_id=flow.company_id,
        ).first()

        if definition is None:
            continue

        object_id = str(request.object_id)

        if WorkflowInstance.objects.filter(
            module=flow.module,
            document_type=flow.document_type,
            object_id=object_id,
        ).exists():
            continue

        instance = WorkflowInstance.objects.create(
            definition=definition,
            module=flow.module,
            document_type=flow.document_type,
            object_id=object_id,
            document_number="",
            document_label="",
            subject_employee_id=request.subject_employee_id,
            company_id=flow.company_id,
            status=INSTANCE_STATUS_MAP.get(request.status, "pending"),
            submitted_by_id=request.submitted_by_id,
            submitted_at=request.submitted_at,
            completed_at=request.completed_at,
            notes=request.notes,
            context={},
        )

        current_step = None

        for action in request.actions.filter(is_deleted=False).order_by(
            "sequence",
        ):
            step = step_map.get(action.step_id)

            if step is None:
                continue

            # Approver lama disimpan sebagai Employee; engine baru
            # memutuskan lewat akun. Pegawai yang belum punya akun
            # tetap dibawa sebagai `approver_employee` supaya kotak
            # tanda tangannya tidak kosong di formulir tercetak.
            approver_user_id = None

            if action.approver_id is not None:
                approver_user_id = (
                    apps.get_model("hr", "Employee")
                    .objects
                    .filter(pk=action.approver_id)
                    .values_list("user_id", flat=True)
                    .first()
                )

            status = APPROVAL_STATUS_MAP.get(action.decision, "pending")

            WorkflowApproval.objects.create(
                instance=instance,
                step=step,
                name=action.name,
                sequence=action.sequence,
                approver_id=approver_user_id,
                approver_employee_id=action.approver_id,
                acted_by_id=action.acted_by_id,
                status=status,
                is_required=step.is_required,
                comment=action.notes,
                acted_at=action.decided_at,
                assignment_type="",
                assignment_reference="Dipindahkan dari engine approval lama.",
                metadata={"legacy_action_id": action.pk},
            )

            if status == "pending" and current_step is None:
                current_step = step

        if instance.status == "pending":
            instance.current_step = current_step

            instance.save(update_fields=["current_step"])


def backwards(apps, schema_editor):
    """
    Sengaja tidak menulis balik ke tabel lama.

    Migration berikutnya menghapus modelnya, jadi rollback yang
    "mengembalikan" data akan menulis ke tabel yang sudah tidak ada.
    Membiarkan data baru berdiri sendiri lebih jujur daripada rollback
    yang gagal separuh jalan.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0001_initial"),
        ("framework", "0002_alter_approvalaction_decision_and_more"),
        ("hr", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
