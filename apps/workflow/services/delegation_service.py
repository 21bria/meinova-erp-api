"""
Surat kuasa: siapa boleh memutuskan atas nama siapa.

Dipakai di dua tempat dan hanya dua: saat menyusun kotak masuk (kuasa
membuat dokumen milik atasan ikut muncul di daftar delegate) dan saat
memeriksa hak memutuskan. Baris keputusannya sendiri tidak disentuh —
`approver` tetap atasan yang seharusnya menandatangani, `acted_by`
yang mencatat siapa yang benar-benar menekan tombolnya.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from apps.core.services.master import BaseMasterService

from apps.workflow.models import WorkflowDelegation


# Kuasa berantai: A menguasakan ke B, B sedang cuti juga dan
# menguasakan ke C. Dibatasi supaya rantai yang berputar (A→B, B→A)
# berhenti sendiri — datanya tidak dijaga di level database.
MAX_DELEGATION_DEPTH = 5


class WorkflowDelegationService(BaseMasterService):
    model = WorkflowDelegation

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        return cls.assert_no_overlap(data)

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        return cls.assert_no_overlap(data, instance=instance)

    @classmethod
    def assert_no_overlap(
        cls,
        data: dict[str, Any],
        *,
        instance: WorkflowDelegation | None = None,
    ) -> dict[str, Any]:
        """
        Menolak dua kuasa aktif yang tumpang tindih untuk cakupan yang
        sama.

        Kalau dibiarkan, satu baris keputusan punya dua delegate yang
        sama-sama berhak dan siapa yang boleh menekan tombolnya jadi
        soal urutan `id`. Tumpang tindih dengan cakupan **berbeda**
        tetap boleh — itu justru gunanya cakupan.
        """

        def resolved(field_name, default=None):
            if field_name in data:
                return data[field_name]

            return getattr(instance, field_name, default)

        delegator = resolved("delegator")
        starts_at = resolved("starts_at")
        ends_at = resolved("ends_at")

        if delegator is None or starts_at is None or ends_at is None:
            return data

        module = resolved("module", "") or ""
        document_type = resolved("document_type", "") or ""

        clashing = (
            WorkflowDelegation.objects
            .filter(
                delegator=delegator,
                is_active=True,
                is_deleted=False,
                starts_at__lt=ends_at,
                ends_at__gt=starts_at,
            )
            .exclude(pk=getattr(instance, "pk", None))
            # Kosong berarti "semua", jadi kuasa tanpa cakupan bentrok
            # dengan kuasa bercakupan apa pun — dan sebaliknya.
            .filter(Q(module="") | Q(module=module) if module else Q())
            .filter(
                Q(document_type="") | Q(document_type=document_type)
                if document_type
                else Q()
            )
            .first()
        )

        if clashing is not None:
            raise ValidationError(
                {
                    "starts_at": (
                        f"{delegator} sudah punya surat kuasa aktif "
                        f"yang bertumpang tindih "
                        f"({clashing.starts_at:%d/%m/%Y} – "
                        f"{clashing.ends_at:%d/%m/%Y}). Batasi "
                        "cakupannya atau ubah periodenya."
                    ),
                },
            )

        return data

    # ------------------------------------------------------------------
    # Pencarian
    # ------------------------------------------------------------------

    @staticmethod
    def active_for(
        *,
        delegator,
        module: str = "",
        document_type: str = "",
        at=None,
    ) -> list[WorkflowDelegation]:
        """Kuasa yang sedang berlaku yang diberikan `delegator`."""
        if delegator is None:
            return []

        at = at or timezone.now()

        return [
            delegation
            for delegation in (
                WorkflowDelegation.objects
                .filter(
                    delegator=delegator,
                    is_active=True,
                    is_deleted=False,
                    starts_at__lte=at,
                    ends_at__gte=at,
                )
                .select_related("delegator", "delegate")
            )
            if delegation.covers(
                module=module,
                document_type=document_type,
            )
        ]

    @classmethod
    def delegation_between(
        cls,
        *,
        approver,
        actor,
        module: str = "",
        document_type: str = "",
        at=None,
    ) -> WorkflowDelegation | None:
        """
        Surat kuasa yang membuat `actor` boleh memutuskan atas nama
        `approver`. None = tidak ada.

        Ditelusuri berantai supaya kuasa bertingkat (A→B, B→C) tetap
        terbaca, dengan pagar kedalaman terhadap rantai yang berputar.
        Yang dikembalikan **kuasa pertama** — itu yang menjelaskan
        kenapa dokumen ini keluar dari tangan approver aslinya, dan itu
        yang perlu dicetak.
        """
        if approver is None or actor is None:
            return None

        frontier = [(approver, None)]
        seen = {approver.pk}

        for _ in range(MAX_DELEGATION_DEPTH):
            next_frontier = []

            for current, origin in frontier:
                for delegation in cls.active_for(
                    delegator=current,
                    module=module,
                    document_type=document_type,
                    at=at,
                ):
                    root = origin or delegation

                    if delegation.delegate_id == actor.pk:
                        return root

                    if delegation.delegate_id in seen:
                        continue

                    seen.add(delegation.delegate_id)

                    next_frontier.append((delegation.delegate, root))

            if not next_frontier:
                return None

            frontier = next_frontier

        return None

    @classmethod
    def delegators_for(
        cls,
        *,
        delegate,
        module: str = "",
        document_type: str = "",
        at=None,
    ) -> list:
        """
        Semua orang yang dokumennya boleh diputuskan `delegate`.

        Dipakai menyusun kotak masuk: tanpa ini, delegate tidak pernah
        melihat dokumen yang sedang jadi tanggung jawabnya dan kuasanya
        cuma jadi baris di master.
        """
        if delegate is None:
            return []

        at = at or timezone.now()

        result = []
        seen = {delegate.pk}
        frontier = [delegate]

        for _ in range(MAX_DELEGATION_DEPTH):
            received = [
                delegation
                for delegation in (
                    WorkflowDelegation.objects
                    .filter(
                        delegate__in=frontier,
                        is_active=True,
                        is_deleted=False,
                        starts_at__lte=at,
                        ends_at__gte=at,
                    )
                    .select_related("delegator")
                )
                if delegation.covers(
                    module=module,
                    document_type=document_type,
                )
            ]

            frontier = []

            for delegation in received:
                if delegation.delegator_id in seen:
                    continue

                seen.add(delegation.delegator_id)

                result.append(delegation.delegator)
                frontier.append(delegation.delegator)

            if not frontier:
                break

        return result
