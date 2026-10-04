"""
Menjalankan alur: mengajukan, menyetujui, menolak, mengembalikan,
membatalkan.

Service ini tidak tahu apa-apa tentang modul yang memakainya. Dokumen
cuma perlu memberi tiga hal: kunci alurnya (`module` + `document_type`),
pegawai yang jadi subjeknya, dan dirinya sendiri sebagai objek yang
ditunjuk. Perpindahan status dokumen sendiri — `LeaveStatus`,
`TravelRequestStatus`, dan seterusnya — tetap urusan modulnya, lewat
callback `on_complete`; engine ini tidak boleh menebak nama kolom status
modul lain. Menebaknya adalah cara tercepat membuat engine ini pecah
saat dipasang ke modul kedua.
"""

from __future__ import annotations

from typing import Any, Callable

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.workflow import conditions, notifications
from apps.workflow.models import (
    OPEN_STATUSES,
    ApprovalMode,
    ApprovalStatus,
    InstanceStatus,
    WorkflowApproval,
    WorkflowInstance,
)
from apps.workflow.resolver import resolve_approvers
from apps.workflow.services.approval_service import (
    WorkflowApprovalService,
)
from apps.workflow.services.definition_service import (
    WorkflowDefinitionResolver,
)


CompleteCallback = Callable[[WorkflowInstance, str], Any]


class WorkflowService:
    # ------------------------------------------------------------------
    # Pencarian
    # ------------------------------------------------------------------

    @staticmethod
    def instance_for(
        *,
        document,
        module: str,
        document_type: str,
        open_only: bool = True,
    ) -> WorkflowInstance | None:
        """Pengajuan dokumen ini. `open_only` = yang masih berjalan."""
        queryset = (
            WorkflowInstance.objects
            .filter(
                module=module,
                document_type=document_type,
                object_id=str(document.pk),
            )
            .select_related("definition", "current_step")
        )

        if open_only:
            queryset = queryset.filter(status__in=OPEN_STATUSES)

        return queryset.order_by("-id").first()

    @staticmethod
    def history_for(*, document, module: str, document_type: str):
        """Seluruh pengajuan dokumen ini, terbaru lebih dulu."""
        return (
            WorkflowInstance.objects
            .filter(
                module=module,
                document_type=document_type,
                object_id=str(document.pk),
            )
            .select_related("definition")
            .prefetch_related("approvals__step", "approvals__approver")
            .order_by("-id")
        )

    # ------------------------------------------------------------------
    # Mengajukan
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def submit(
        cls,
        *,
        document,
        module: str,
        document_type: str,
        employee=None,
        user=None,
        context: dict | None = None,
        document_number: str = "",
        document_label: str = "",
        notes: str = "",
        scope: dict | None = None,
        initiator_employee=None,
        on_complete: CompleteCallback | None = None,
    ) -> WorkflowInstance:
        """
        Memulai alur untuk satu dokumen.

        `initiator_employee` adalah **pengusulnya** — pegawai yang
        bertanggung jawab atas isi dokumen, yang belum tentu sama
        dengan `user` yang mengetiknya. Kalau ia kebetulan juga
        approver di salah satu meja, meja itu ditandai SKIPPED: tidak
        ada yang diminta menyetujui usulannya sendiri. Kosong =
        perilaku lama, seluruh meja berjalan seperti biasa.

        Seluruh baris keputusan dibuat di depan, lengkap dengan nama
        approver-nya. Dua alasan: formulir yang dicetak harus
        memperlihatkan semua kotak tanda tangan sejak awal, dan
        approver-nya harus dibekukan — mutasi atasan minggu depan tidak
        boleh mengubah siapa yang seharusnya menandatangani dokumen yang
        sudah berjalan.
        """
        running = cls.instance_for(
            document=document,
            module=module,
            document_type=document_type,
        )

        if running is not None:
            if running.status != InstanceStatus.RETURNED:
                raise ValidationError(
                    {
                        "workflow": (
                            "Dokumen ini sudah diajukan dan masih "
                            "menunggu persetujuan."
                        ),
                    },
                )

            # Dokumen yang dikembalikan lalu diperbaiki: pengajuan
            # lamanya ditutup dan yang baru berdiri sendiri. Sengaja
            # bukan menyalakan ulang baris yang sama — jejak siapa yang
            # mengembalikan dan alasannya harus tetap terbaca, dan
            # menimpanya berarti riwayat revisi hilang.
            cls._close(
                instance=running,
                status=InstanceStatus.CANCELLED,
                user=user,
                note="Ditutup otomatis karena dokumennya diajukan ulang.",
            )

        scope = scope or WorkflowDefinitionResolver.scope_from_employee(
            employee,
        )

        definition = WorkflowDefinitionResolver.match(
            module=module,
            document_type=document_type,
            **scope,
        )

        if definition is None:
            raise ValidationError(
                {
                    "workflow": (
                        f"Belum ada alur aktif untuk "
                        f"{module}/{document_type} yang cocok dengan "
                        "penempatan pegawai ini. Periksa Workflow "
                        "Definition, atau seed lewat seed_workflows."
                    ),
                },
            )

        steps = list(
            definition.steps
            .filter(is_deleted=False, is_active=True)
            .select_related("approver_user", "approver_role", "fallback_role")
            .order_by("sequence"),
        )

        if not steps:
            raise ValidationError(
                {
                    "workflow": (
                        f"Alur {definition.code} belum punya satu step "
                        "pun."
                    ),
                },
            )

        instance = WorkflowInstance.objects.create(
            definition=definition,
            module=module,
            document_type=document_type,
            object_id=str(document.pk),
            document_number=document_number,
            document_label=document_label,
            subject_employee=employee,
            company=scope.get("company"),
            branch=scope.get("branch"),
            location=scope.get("location"),
            status=InstanceStatus.PENDING,
            submitted_by=user,
            submitted_at=timezone.now(),
            notes=notes,
            context=context or {},
        )

        cls._build_approvals(
            instance=instance,
            steps=steps,
            employee=employee,
            company=scope.get("company"),
            initiator_employee=initiator_employee,
        )

        # Seluruh step ternyata terlewat — semuanya tidak wajib dan
        # approver-nya tidak ketemu, atau syaratnya tidak terpenuhi.
        # Dokumennya langsung selesai, dan `on_complete` tetap dipanggil
        # supaya modulnya ikut memindahkan status. Jarang, tapi bukan
        # kesalahan.
        cls._advance(instance=instance, user=user, on_complete=on_complete)

        return instance

    @classmethod
    def _build_approvals(
        cls,
        *,
        instance,
        steps,
        employee,
        company,
        initiator_employee=None,
    ) -> None:
        """
        Menyusun seluruh kotak tanda tangan sekaligus.

        Kegagalan menemukan approver pada step wajib membatalkan
        **seluruh** pengajuan (transaksi rollback), dengan pesan yang
        menyebut kolom mana yang kosong. Dokumen yang berjalan dengan
        satu kotak kosong akan mengendap tanpa ada yang merasa ditagih.
        """
        unresolved: list[str] = []

        # Approver yang sudah kebagian kotak. Di struktur ramping satu
        # orang lazim jadi atasan langsung sekaligus kepala departemen;
        # barisnya tetap dicetak dengan namanya plus keterangan bahwa
        # persetujuannya sudah terwakili — memintanya menekan tombol dua
        # kali tidak menambah kendali apa pun.
        assigned: dict[int, str] = {}

        # Pengusul tidak diminta menyetujui usulannya sendiri.
        #
        # Barisnya tetap dicetak dengan namanya — kotak tanda tangan
        # atasan wajib ada di dokumen tercetak — cuma ditandai SKIPPED
        # dengan keterangan bahwa dialah yang mengajukan. Menghapus
        # barisnya membuat formulir kehilangan kotak yang secara
        # administratif harus ada; membiarkannya PENDING berarti satu
        # klik yang hasilnya sudah pasti.
        initiator_user_id = getattr(initiator_employee, "user_id", None)

        if initiator_user_id:
            assigned[initiator_user_id] = (
                "Diajukan olehnya — pengusul tidak diminta menyetujui "
                "usulannya sendiri."
            )

        now = timezone.now()

        for step in steps:
            if not conditions.evaluate(step.condition, instance.context):
                WorkflowApproval.objects.create(
                    instance=instance,
                    step=step,
                    name=step.name,
                    sequence=step.sequence,
                    approver=None,
                    status=ApprovalStatus.SKIPPED,
                    is_required=step.is_required,
                    acted_at=now,
                    assignment_reference=(
                        "Syarat step ini tidak terpenuhi oleh dokumen."
                    ),
                    metadata={"condition": step.condition},
                )

                continue

            resolved = resolve_approvers(
                employee=employee,
                step=step,
                company=company,
            )

            if not resolved.found:
                if step.is_required:
                    unresolved.append(
                        f"Step #{step.sequence} ({step.name}): "
                        f"{resolved.reason}",
                    )

                    continue

                WorkflowApproval.objects.create(
                    instance=instance,
                    step=step,
                    name=step.name,
                    sequence=step.sequence,
                    approver=None,
                    status=ApprovalStatus.SKIPPED,
                    is_required=False,
                    acted_at=now,
                    assignment_reference=(
                        f"Dilewati otomatis — {resolved.reason}"
                    ),
                )

                continue

            for candidate in resolved.candidates:
                already = assigned.get(candidate.user.pk)

                WorkflowApproval.objects.create(
                    instance=instance,
                    step=step,
                    name=step.name,
                    sequence=step.sequence,
                    approver=candidate.user,
                    approver_employee=candidate.employee,
                    status=(
                        ApprovalStatus.SKIPPED
                        if already
                        else ApprovalStatus.PENDING
                    ),
                    is_required=step.is_required,
                    acted_at=now if already else None,
                    assignment_type=candidate.assignment_type,
                    assignment_reference=already or candidate.reason,
                    metadata=cls._resolution_metadata(candidate),
                )

                if not already:
                    assigned[candidate.user.pk] = (
                        f"Sudah terwakili step #{step.sequence} — orang "
                        "yang sama memegang kedua peran."
                    )

        if unresolved:
            # Ditolak seluruhnya, bukan dijalankan dengan satu meja
            # kosong — dan kalimatnya menyebut ini kesalahan
            # **konfigurasi**, bukan kesalahan pengaju. Yang membaca
            # pesan ini lazimnya orang yang menekan Submit, dan tanpa
            # kata itu ia akan menyunting dokumennya berulang kali
            # untuk memperbaiki hal yang tidak ada hubungannya.
            #
            # Dokumennya sendiri tidak bergerak: tidak ada
            # `WorkflowInstance` yang terbentuk, jadi setelah datanya
            # dilengkapi Submit yang sama diulang pada dokumen yang
            # sama — tanpa ada pengajuan baru yang dibuat.
            raise ValidationError(
                {
                    "workflow": (
                        "CONFIGURATION ERROR — approver belum bisa "
                        "ditentukan, jadi pengajuannya belum dibuat. "
                        "Lengkapi data di bawah lalu ajukan lagi "
                        "dokumen yang sama:\n"
                        + "\n".join(unresolved)
                    ),
                },
            )

    @staticmethod
    def _resolution_metadata(candidate) -> dict:
        """
        Jejak resolusi satu kotak tanda tangan, dalam bentuk nilai.

        `assignment_reference` sudah menjelaskannya dalam kalimat, dan
        itu yang dibaca orang — tapi kalimat tidak bisa disaring atau
        dihitung. Yang disimpan di sini menjawab pertanyaan yang tidak
        bisa dijawab teks bebas: berapa banyak meja yang terisi lewat
        cadangan, dan cadangan tingkat mana. Itu yang memberi tahu baris
        master mana yang harus diisi lebih dulu.

        Ditulis apa adanya, bukan digabung dengan metadata lain: satu
        baris keputusan hanya pernah punya satu resolusi.
        """
        return {
            "resolution_source": candidate.resolution_source,
            "resolved_role": candidate.resolved_role,
            "resolved_scope": candidate.resolved_scope,
            "resolved_scope_object": candidate.resolved_scope_object,
            "resolved_scope_object_id": candidate.resolved_scope_object_id,
        }

    # ------------------------------------------------------------------
    # Keputusan
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def approve(cls, *, instance, user=None, comment: str = "", on_complete=None):
        return cls._decide(
            instance=instance,
            user=user,
            decision=ApprovalStatus.APPROVED,
            comment=comment,
            on_complete=on_complete,
        )

    @classmethod
    @transaction.atomic
    def reject(cls, *, instance, user=None, comment: str = "", on_complete=None):
        return cls._decide(
            instance=instance,
            user=user,
            decision=ApprovalStatus.REJECTED,
            comment=comment,
            on_complete=on_complete,
        )

    @classmethod
    @transaction.atomic
    def send_back(cls, *, instance, user=None, comment: str = "", on_complete=None):
        """
        Mengembalikan dokumen ke pengaju untuk diperbaiki.

        Bukan penolakan: dokumennya boleh disunting lalu diajukan ulang,
        dan alurnya berangkat dari step pertama lagi. Tanpa jalur ini,
        satu tanggal yang salah ketik hanya punya dua pilihan — ditolak
        (dan pengajunya harus membuat dokumen baru) atau disetujui
        dengan isi yang salah.
        """
        return cls._decide(
            instance=instance,
            user=user,
            decision=ApprovalStatus.RETURNED,
            comment=comment,
            on_complete=on_complete,
        )

    @classmethod
    def _decide(
        cls,
        *,
        instance,
        user,
        decision: str,
        comment: str = "",
        on_complete: CompleteCallback | None = None,
    ) -> WorkflowInstance:
        if instance.status != InstanceStatus.PENDING:
            raise ValidationError(
                {
                    "workflow": (
                        f"Dokumen berstatus "
                        f"{instance.get_status_display()} tidak sedang "
                        "menunggu persetujuan."
                    ),
                },
            )

        approval, right = cls._actionable_row(instance=instance, user=user)

        step = approval.step

        if decision == ApprovalStatus.REJECTED and not step.can_reject:
            raise ValidationError(
                {
                    "workflow": (
                        f"Step '{step.name}' tidak mengizinkan "
                        "penolakan."
                    ),
                },
            )

        if decision == ApprovalStatus.RETURNED and not step.can_return:
            raise ValidationError(
                {
                    "workflow": (
                        f"Step '{step.name}' tidak mengizinkan dokumen "
                        "dikembalikan."
                    ),
                },
            )

        approval.status = decision
        approval.acted_by = user
        approval.acted_via_delegation = right.delegation
        approval.acted_at = timezone.now()
        approval.comment = comment

        approval.save(
            update_fields=[
                "status",
                "acted_by",
                "acted_via_delegation",
                "acted_at",
                "comment",
                "updated_at",
            ],
        )

        if decision == ApprovalStatus.REJECTED:
            cls._cancel_pending(instance, note="Dokumen ditolak.")

            cls._close(
                instance=instance,
                status=InstanceStatus.REJECTED,
                user=user,
            )

            notifications.notify_outcome(
                instance,
                "rejected",
                decided_by=user,
                comment=comment,
            )

            cls._notify(on_complete, instance, InstanceStatus.REJECTED)

            return instance

        if decision == ApprovalStatus.RETURNED:
            cls._cancel_pending(
                instance,
                note="Dokumen dikembalikan ke pengaju.",
            )

            instance.status = InstanceStatus.RETURNED
            instance.current_step = None

            instance.save(
                update_fields=["status", "current_step", "updated_at"],
            )

            notifications.notify_outcome(
                instance,
                "returned",
                decided_by=user,
                comment=comment,
            )

            cls._notify(on_complete, instance, InstanceStatus.RETURNED)

            return instance

        return cls._advance(instance=instance, user=user, on_complete=on_complete)

    @classmethod
    def _actionable_row(cls, *, instance, user):
        """
        Baris di step berjalan yang boleh diputuskan `user`.

        Alasan penolakan yang paling spesifik yang dilaporkan: "menunggu
        keputusan Budi" jauh lebih berguna daripada "tidak berhak", dan
        itu hanya bisa disusun setelah semua baris diperiksa.
        """
        rows = list(
            instance.pending_approvals
            .select_related("step", "approver", "instance")
        )

        if not rows:
            raise ValidationError(
                {"workflow": "Tidak ada step yang menunggu keputusan."},
            )

        reasons = []

        for approval in rows:
            right = WorkflowApprovalService.check_right(
                approval=approval,
                user=user,
            )

            if right:
                return approval, right

            reasons.append(right.reason)

        raise ValidationError(
            {"workflow": " ".join(dict.fromkeys(reasons))},
        )

    # ------------------------------------------------------------------
    # Perpindahan step
    # ------------------------------------------------------------------

    @classmethod
    def _advance(
        cls,
        *,
        instance,
        user=None,
        on_complete: CompleteCallback | None = None,
    ) -> WorkflowInstance:
        """
        Memindahkan dokumen ke step berikutnya yang masih menunggu.

        Dijalankan ulang dari awal daftar tiap kali, bukan disimpan
        sebagai penunjuk yang digeser: step yang seluruh barisnya
        SKIPPED harus terlewati sendiri, dan menghitung ulang membuat
        keadaan tidak bisa hanyut.
        """
        rows = list(
            instance.approvals
            .select_related("step")
            .order_by("sequence", "id")
        )

        current_step_id = None

        for approval in rows:
            if approval.status != ApprovalStatus.PENDING:
                continue

            step_rows = [
                row
                for row in rows
                if row.step_id == approval.step_id
            ]

            if cls._step_satisfied(approval.step, step_rows):
                # Mode Any Approver yang sudah cukup persetujuannya:
                # sisa approver tidak perlu ditagih lagi. Ditandai
                # SKIPPED dengan alasannya, bukan dihapus — kotak tanda
                # tangannya tetap tercetak.
                cls._skip_remaining(step_rows)

                continue

            current_step_id = approval.step_id

            break

        if current_step_id is not None:
            moved = instance.current_step_id != current_step_id

            if moved:
                instance.current_step_id = current_step_id

                instance.save(
                    update_fields=["current_step", "updated_at"],
                )

            # Menagih meja yang baru kebagian. **Hanya saat berpindah** —
            # `_advance` dipanggil ulang dari awal daftar tiap kali, jadi
            # tanpa penjagaan ini approver ditagih lagi setiap ada
            # keputusan di dokumen yang sama.
            #
            # Baris pertama (saat submit) ikut terhitung berpindah:
            # `current_step_id` masih None sebelum ini.
            if moved:
                notifications.notify_pending(instance)

            return instance

        cls._close(
            instance=instance,
            status=InstanceStatus.APPROVED,
            user=user,
        )

        notifications.notify_outcome(
            instance,
            "approved",
            decided_by=user,
        )

        cls._notify(on_complete, instance, InstanceStatus.APPROVED)

        return instance

    @staticmethod
    def _step_satisfied(step, rows) -> bool:
        approved = sum(
            1
            for row in rows
            if row.status == ApprovalStatus.APPROVED
        )

        if step.approval_mode == ApprovalMode.ALL:
            return not any(
                row.status == ApprovalStatus.PENDING
                for row in rows
            )

        return approved >= max(1, step.minimum_approvals)

    @staticmethod
    def _skip_remaining(rows) -> None:
        now = timezone.now()

        for row in rows:
            if row.status != ApprovalStatus.PENDING:
                continue

            row.status = ApprovalStatus.SKIPPED
            row.acted_at = now
            row.assignment_reference = (
                "Step sudah terpenuhi oleh approver lain."
            )

            row.save(
                update_fields=[
                    "status",
                    "acted_at",
                    "assignment_reference",
                    "updated_at",
                ],
            )

    # ------------------------------------------------------------------
    # Pembatalan & penutupan
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def cancel(
        cls,
        *,
        instance,
        user=None,
        comment: str = "",
        on_complete: CompleteCallback | None = None,
    ) -> WorkflowInstance:
        """Menarik kembali pengajuan yang belum selesai."""
        if not instance.is_open:
            raise ValidationError(
                {
                    "workflow": (
                        f"Dokumen berstatus "
                        f"{instance.get_status_display()} tidak bisa "
                        "ditarik."
                    ),
                },
            )

        cls._cancel_pending(instance, note="Pengajuan ditarik pengaju.")

        cls._close(
            instance=instance,
            status=InstanceStatus.CANCELLED,
            user=user,
            note=comment,
        )

        cls._notify(on_complete, instance, InstanceStatus.CANCELLED)

        return instance

    @staticmethod
    def _cancel_pending(instance, *, note: str) -> None:
        now = timezone.now()

        for row in instance.approvals.filter(status=ApprovalStatus.PENDING):
            row.status = ApprovalStatus.CANCELLED
            row.acted_at = now
            row.assignment_reference = note

            row.save(
                update_fields=[
                    "status",
                    "acted_at",
                    "assignment_reference",
                    "updated_at",
                ],
            )

    @staticmethod
    def _close(*, instance, status, user=None, note: str = ""):
        instance.status = status
        instance.current_step = None
        instance.completed_at = timezone.now()

        if note:
            instance.notes = (
                f"{instance.notes}\n{note}".strip()
                if instance.notes
                else note
            )

        instance.save(
            update_fields=[
                "status",
                "current_step",
                "completed_at",
                "notes",
                "updated_at",
            ],
        )

        return instance

    @staticmethod
    def _notify(callback: CompleteCallback | None, instance, status) -> None:
        """
        Memberi tahu modul pemilik dokumen bahwa alurnya berhenti.

        Hanya dipanggil saat alurnya benar-benar berpindah keadaan.
        Di situlah modul memindahkan status dokumennya sendiri — engine
        ini sengaja tidak menyentuh kolom status milik modul lain.
        """
        if callback is not None:
            callback(instance, status)
