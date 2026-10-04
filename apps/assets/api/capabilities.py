"""
Kapabilitas aksi per record — "bolehkah **saya** menekan tombol ini pada
dokumen **ini**" (ASSET-6).

`MRecordActions` di frontend hanya mengenal izin model + `visible_when`,
padahal Transfer/Return punya wewenang per sisi (submit dari asal,
complete dari tujuan, §17). Tanpa jawaban server, tombol Complete tampil
untuk admin sisi asal lalu dibalas 404 — benar secara keamanan, menyesatkan
secara tampilan.

Jawabannya dihitung dengan **jalur yang sama** dengan penegakannya:
izin model (`user.has_perm`, juga dicek service) + cakupan data yang
dipakai `filter_queryset` untuk aksi itu (sisi dari `action_sides` bila
viewset dua sisi, `data_scope` bila satu sisi). Ini tampilan, bukan
penjagaan: backend tetap menolak sendiri.
"""

from __future__ import annotations

from apps.accounts.scoping import DataScopeService


def _sides_for(view, action: str) -> list[dict]:
    scope_sides = getattr(view, "scope_sides", None)

    if scope_sides:
        names = view.action_sides.get(action, view.visible_sides)

        return [scope_sides[name] for name in names]

    mapping = getattr(view, "data_scope", None)

    return [mapping] if mapping else []


def action_allowed(view, instance, action: str, permission: str) -> bool:
    request = getattr(view, "request", None)
    user = getattr(request, "user", None)

    if user is None or not user.is_authenticated:
        return False

    if not user.has_perm(permission):
        return False

    sides = _sides_for(view, action)

    if not sides:
        return True

    queryset = type(instance).objects.filter(pk=instance.pk)

    return any(
        DataScopeService.filter(
            queryset,
            mapping,
            user,
            required_permission=permission,
        ).exists()
        for mapping in sides
    )


def capabilities(view, instance, actions: dict[str, str]) -> dict[str, bool] | None:
    """
    `{"can_<aksi>": bool}` untuk setiap `{aksi: izin}`. Hanya untuk satu
    record yang dibuka (retrieve dan aksi detail) — di daftar mengembalikan
    `None`, karena tiap baris berarti beberapa query dan tabel tidak
    menampilkan tombolnya.
    """
    if view is None or getattr(view, "action", None) == "list":
        return None

    return {
        f"can_{name}": action_allowed(view, instance, name, permission)
        for name, permission in actions.items()
    }


def movement_document_capabilities(view, instance, *, model_name: str) -> dict | None:
    """
    Kapabilitas dokumen pergerakan (Assignment/Return/Transfer) — izin +
    sisi **dan** status, supaya layar tidak perlu menyalin daftar status
    yang boleh apa (pola `can_edit`/`can_save`/`can_delete`,
    `generator-schema.md`).
    """
    status = instance.status
    draft = status == "DRAFT"
    running = status in ("SUBMITTED", "APPROVED")

    allowed = capabilities(view, instance, {
        "update": f"assets.change_{model_name}",
        "destroy": f"assets.delete_{model_name}",
        "submit": f"assets.submit_{model_name}",
        "cancel": f"assets.cancel_{model_name}",
        "complete": f"assets.complete_{model_name}",
    })

    if allowed is None:
        return None

    return {
        "can_edit": draft and allowed["can_update"],
        "can_save": draft and allowed["can_update"],
        "can_delete": draft and allowed["can_destroy"],
        "can_submit": draft and allowed["can_submit"],
        "can_cancel": running and allowed["can_cancel"],
        "can_complete": status == "APPROVED" and allowed["can_complete"],
        "approval": workflow_approval(view, instance),
    }


def workflow_approval(view, instance) -> dict | None:
    """
    Keadaan persetujuan dokumen — **bentuk yang sama** dengan blok
    `approval` dokumen HR/Payroll (`approval.can_act` dibaca `visible_when`
    tombol Approve/Reject; `steps` dirender `WorkflowApprovalTrail`).

    Hak memutuskan ditanyakan ke engine (`WorkflowApprovalService.can_act`:
    pemegang meja, penerima kuasa, superuser) — bukan dari izin model
    atau sisi dokumen. Pemegang aset tidak otomatis approver (O-4).
    """
    from apps.workflow.models import ApprovalStatus
    from apps.workflow.services.approval_service import WorkflowApprovalService
    from apps.workflow.services.workflow_service import WorkflowService

    module, document_type = getattr(view, "workflow_document", None) or (None, None)

    if not module:
        return None

    workflow = WorkflowService.history_for(
        document=instance,
        module=module,
        document_type=document_type,
    ).first()

    if workflow is None:
        return None

    user = getattr(getattr(view, "request", None), "user", None)

    rows = sorted(workflow.approvals.all(), key=lambda row: (row.sequence, row.pk))

    current = next(
        (
            row
            for row in rows
            if row.status == ApprovalStatus.PENDING
            and row.step_id == workflow.current_step_id
        ),
        None,
    )

    def approver_name(row):
        if row.approver_employee_id:
            return row.approver_employee.full_name

        if row.approver_id:
            return row.approver.get_full_name() or row.approver.email

        return None

    return {
        "instance_id": workflow.pk,
        "status": workflow.status,
        "status_label": workflow.get_status_display(),
        "flow": workflow.definition.name,
        "submitted_at": workflow.submitted_at,
        "completed_at": workflow.completed_at,
        "can_act": (
            current is not None
            and WorkflowApprovalService.can_act(approval=current, user=user)
        ),
        "current_step": (
            {
                "approval_id": current.pk,
                "sequence": current.sequence,
                "name": current.name,
                "approver": approver_name(current),
            }
            if current is not None
            else None
        ),
        "steps": [
            {
                "approval_id": row.pk,
                "sequence": row.sequence,
                "name": row.name,
                "approver": approver_name(row),
                "decision": row.status,
                "decision_label": row.get_status_display(),
                "decided_at": row.acted_at,
                "notes": row.comment or row.assignment_reference,
            }
            for row in rows
        ],
    }


class CapabilityFieldsMixin:
    """
    Menambahkan kapabilitas sebagai field tingkat atas pada representasi
    satu record. Serializer menimpa `record_capabilities(instance)`.
    """

    def record_capabilities(self, instance) -> dict | None:  # pragma: no cover
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)

        extra = self.record_capabilities(instance)

        if extra:
            data.update(extra)

        return data
