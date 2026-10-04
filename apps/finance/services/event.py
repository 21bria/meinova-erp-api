"""
Pemroses kejadian akuntansi — pintu masuk modul lain ke Finance.

Kontraknya satu fungsi:

    AccountingEventProcessor.record(
        event_type="PAYROLL_POSTED",
        source_module="payroll",
        source_type="payroll_run",
        source_id=str(run.pk),
        company=run.company,
        event_date=run.period.end_date,
        payload={...},
        idempotency_key=f"payroll:payroll_run:{run.pk}:posted",
    )

Modul sumber tidak menyebut satu pun kode akun, tidak mengenal satu pun
model Finance selain fungsi ini, dan tidak perlu tahu apakah tenant
yang bersangkutan memang membukukan kejadian itu.
"""

from __future__ import annotations

import json
import logging
from datetime import date

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from rest_framework.exceptions import PermissionDenied

from apps.accounts.scoping import DataScopeService

from apps.finance.models import (
    IMMUTABLE_JOURNAL_STATUSES,
    ZERO,
    AccountingEvent,
    AccountingEventStatus,
    Journal,
    JournalStatus,
    JournalType,
    PostingSide,
)
from apps.finance.services.fiscal import FiscalPeriodService
from apps.finance.services.journal import JournalService
from apps.finance.services.policy import AccountingPolicyService
from apps.finance.services.posting import FinancePostingService


logger = logging.getLogger(__name__)


#: Izin yang mengotorisasi pemrosesan ulang sebuah kejadian.
#:
#: Izin CRUD bawaan model, bukan izin kustom: memproses ulang **mengubah**
#: kejadian (status, jurnal yang lahir darinya), dan izin tersendiri
#: seperti `retry_accountingevent` butuh migrasi `Meta.permissions` yang
#: tidak disetujui untuk tahap ini. FINANCE-MANAGER dan FINANCE-ADMIN
#: sudah memegangnya lewat seed; role payroll tidak.
RETRY_PERMISSION = "finance.change_accountingevent"

#: Cakupan baris kejadian — sama dengan `data_scope` viewset-nya.
EVENT_SCOPE = {"company": "company"}


class AccountingEventError(ValidationError):
    """
    Kejadian yang **wajib** menerbitkan jurnal tapi tidak berhasil.

    Membawa `error_code` yang bisa dibaca mesin, supaya modul sumber
    bisa meneruskannya tanpa mengurai kalimat — dan tanpa mengimpor satu
    pun model Finance untuk membandingkan status.
    """

    def __init__(self, message: str, *, code: str):
        super().__init__({"accounting_event": [message]}, code=code)
        self.error_code = code


class AccountingEventConflict(AccountingEventError):
    """Penanda yang sama, isi yang berbeda."""


class AccountingEventNotProcessed(AccountingEventError):
    """Kejadiannya tercatat, tapi tidak berakhir dengan jurnal."""


def _normalized(payload) -> str:
    """
    Bentuk pembanding payload: JSON berkunci urut.

    Dibandingkan sesudah melewati JSON karena itu yang disimpan
    `JSONField` — tuple jadi list, dan dict yang sama dengan urutan kunci
    lain harus tetap dianggap sama.
    """
    return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))


class AccountingEventProcessor:
    """Mencatat kejadian, lalu menerbitkan jurnalnya."""

    # ------------------------------------------------------------------
    # Pencatatan
    # ------------------------------------------------------------------

    @classmethod
    def record(
        cls,
        *,
        event_type: str,
        source_module: str,
        company,
        event_date: date,
        idempotency_key: str,
        payload: dict | None = None,
        source_type: str = "",
        source_id: str = "",
        source_reference: str = "",
        user=None,
        process: bool = True,
    ) -> AccountingEvent:
        """
        Mencatat kejadian sekali saja.

        **Kembaran dikembalikan, bukan ditolak.** Modul sumber yang
        di-retry harus bisa memanggil ini berulang kali tanpa menangani
        error apa pun; yang penting jurnalnya tetap satu. Itu sebabnya
        pengembaliannya baris yang sudah ada — pemanggil melihat
        keberhasilan, dan buku besarnya tidak berubah.
        """
        if not idempotency_key:
            raise ValidationError({
                "idempotency_key": (
                    "Kejadian akuntansi wajib membawa penanda unik. "
                    "Tanpa itu, satu retry menerbitkan jurnal kedua dan "
                    "tidak ada yang bisa mencegahnya."
                ),
            })

        existing = (
            AccountingEvent.objects
            .filter(idempotency_key=idempotency_key, is_deleted=False)
            .select_related("generated_journal")
            .first()
        )

        if existing is not None:
            logger.info(
                "Kejadian akuntansi %s sudah tercatat (status %s) — "
                "permintaan ulang diabaikan.",
                idempotency_key,
                existing.status,
            )

            return existing

        try:
            with transaction.atomic():
                event = AccountingEvent(
                    event_type=event_type.strip().upper(),
                    source_module=source_module,
                    source_type=source_type,
                    source_id=str(source_id or ""),
                    source_reference=source_reference,
                    company=company,
                    event_date=event_date,
                    payload=payload or {},
                    idempotency_key=idempotency_key,
                    status=AccountingEventStatus.PENDING,
                    created_by=user,
                )

                event.full_clean(exclude=["generated_journal"])
                event.save()

        except IntegrityError:
            # Dua proses menulis bersamaan. Constraint unik yang
            # memenangkan salah satunya — dan yang kalah membaca hasil
            # pemenangnya, bukan melempar. Inilah kenapa penjagaannya di
            # database dan bukan di `filter().exists()` di atas:
            # pemeriksaan itu punya jendela, constraint tidak.
            logger.info(
                "Kejadian akuntansi %s ditulis proses lain — memakai "
                "baris yang sudah ada.",
                idempotency_key,
            )

            return (
                AccountingEvent.objects
                .filter(idempotency_key=idempotency_key, is_deleted=False)
                .select_related("generated_journal")
                .first()
            )

        if process:
            cls.process(event=event, user=user)

            event.refresh_from_db()

        return event

    @classmethod
    def record_required(
        cls,
        *,
        event_type: str,
        source_module: str,
        company,
        event_date: date,
        idempotency_key: str,
        payload: dict,
        source_type: str = "",
        source_id: str = "",
        source_reference: str = "",
        user=None,
        replaces_key: str = "",
    ) -> AccountingEvent:
        """
        Mencatat dan memproses kejadian yang **harus** menerbitkan jurnal.

        `record()` dibuat untuk dunia yang boleh gagal belakangan: kejadian
        yang gagal ditandai FAILED dan menunggu `retry()`. Modul sumber yang
        menjadikan jurnalnya **syarat** transaksinya sendiri (Finalize
        payroll) butuh kebalikannya — gagal berarti batal seluruhnya. Tiga
        hal yang dijaga di sini:

        1. **Satu unit atomik.** Seluruhnya di dalam `transaction.atomic()`:
           kalau ia melempar, baris kejadian dan jurnal draf yang sempat
           terbit ikut dibatalkan. Dipanggil di dalam transaksi pemanggil,
           ia jadi savepoint dan lemparannya membatalkan transaksi luar.
        2. **Penanda sama, isi berbeda = konflik.** Kembaran yang isinya
           identik dikembalikan apa adanya (idempoten). Kembaran yang
           isinya berbeda **ditolak**, bukan ditimpa dan bukan dicatat
           kedua kalinya — dua kebenaran untuk satu kejadian adalah
           keadaan yang tidak bisa dijelaskan siapa pun sesudahnya.
        3. **Hanya PROCESSED dengan jurnal yang lolos.** SKIPPED (tidak ada
           kebijakan, tidak ada baris), FAILED (pemetaan, periode, akun),
           dan CANCELLED semuanya melempar dengan `error_code` sendiri.

        Kebijakan tetap yang menentukan posting: `process()` dipanggil
        dengan bawaannya, jadi `auto_post` kebijakan itulah yang memutuskan
        jurnalnya diposting atau tinggal DRAFT. Tidak ada `post=False`
        yang dipaksakan di sini.

        `replaces_key` (PF-0G) adalah **penanda** kejadian yang digantikan
        proyeksi ini, bukan objeknya: modul sumber memegang penandanya
        sendiri dan tidak boleh menyentuh model Finance. Kejadiannya
        diresolusi di sini, dan penunjuknya disimpan di metadata jurnal
        yang terbit.
        """
        with transaction.atomic():
            replaces_event = (
                AccountingEvent.objects.filter(
                    idempotency_key=replaces_key,
                ).first()
                if replaces_key
                else None
            )

            event = cls.record(
                event_type=event_type,
                source_module=source_module,
                company=company,
                event_date=event_date,
                idempotency_key=idempotency_key,
                payload=payload,
                source_type=source_type,
                source_id=source_id,
                source_reference=source_reference,
                user=user,
                process=False,
            )

            cls._assert_same_event(
                event=event,
                event_type=event_type,
                source_module=source_module,
                company=company,
                payload=payload,
            )

            if event.status != AccountingEventStatus.PROCESSED:
                event = cls.process(
                    event=event, user=user, replaces_event=replaces_event,
                )

            cls._assert_processed(event)

            return event

    @staticmethod
    def _assert_same_event(*, event, event_type, source_module, company, payload):
        same = (
            event.event_type == event_type.strip().upper()
            and event.source_module == source_module
            and event.company_id == getattr(company, "pk", company)
            and _normalized(event.payload) == _normalized(payload)
        )

        if same:
            return

        raise AccountingEventConflict(
            (
                f"Kejadian akuntansi dengan penanda "
                f"'{event.idempotency_key}' sudah tercatat dengan isi yang "
                "berbeda. Tidak ada yang ditimpa dan tidak ada kejadian "
                "kedua yang dicatat — periksa kejadian yang sudah ada di "
                "Finance → Accounting Events."
            ),
            code="accounting_event_conflict",
        )

    @staticmethod
    def _assert_processed(event) -> None:
        if (
            event.status == AccountingEventStatus.PROCESSED
            and event.generated_journal_id
        ):
            return

        if event.status == AccountingEventStatus.SKIPPED:
            if event.applied_policy_id is None:
                raise AccountingEventNotProcessed(
                    (
                        f"Belum ada kebijakan akuntansi aktif untuk "
                        f"'{event.event_type}' di perusahaan ini. "
                        "Susun kebijakannya di Finance → Setup → "
                        "Accounting Policies."
                    ),
                    code="accounting_policy_missing",
                )

            raise AccountingEventNotProcessed(
                (
                    "Kebijakan akuntansinya cocok, tapi tidak satu aturan "
                    "pun menghasilkan baris jurnal untuk kejadian ini."
                ),
                code="accounting_no_journal_lines",
            )

        if event.status == AccountingEventStatus.CANCELLED:
            raise AccountingEventNotProcessed(
                "Kejadian akuntansi ini sudah dibatalkan.",
                code="accounting_event_cancelled",
            )

        raise AccountingEventNotProcessed(
            (
                "Jurnal tidak bisa diterbitkan: "
                f"{event.error_message or 'sebab tidak tercatat.'}"
            ),
            code="accounting_journal_failed",
        )

    # ------------------------------------------------------------------
    # Pemrosesan
    # ------------------------------------------------------------------

    @classmethod
    def process(
        cls,
        *,
        event: AccountingEvent,
        user=None,
        post: bool = True,
        replaces_event: AccountingEvent | None = None,
    ) -> AccountingEvent:
        """
        Menerbitkan jurnal dari satu kejadian.

        Dikunci lebih dulu dengan `select_for_update()`: dua pemroses
        yang berjalan bersamaan pada kejadian yang sama akan sama-sama
        melihat `PENDING` kalau tidak, dan keduanya menerbitkan jurnal.
        Constraint idempotensi menjaga *kejadiannya* tidak kembar — ia
        tidak menjaga satu kejadian diproses dua kali.
        """
        with transaction.atomic():
            locked = (
                AccountingEvent.objects
                .select_for_update()
                .select_related("company")
                .get(pk=event.pk)
            )

            if locked.status == AccountingEventStatus.PROCESSED:
                return locked

            if locked.status == AccountingEventStatus.CANCELLED:
                return locked

            # PF-0G. Kejadian yang sudah digantikan tidak pernah diproses
            # lagi: jurnalnya sudah dicabut keberlakuannya, dan
            # menerbitkan yang kedua akan menghidupkan fakta yang sudah
            # diganti.
            if locked.status == AccountingEventStatus.SUPERSEDED:
                return locked

            if locked.generated_journal_id:
                # Jejaring pengaman: jurnalnya ada tapi statusnya belum
                # sempat ditulis (proses mati di antara keduanya).
                # Dirapikan, bukan diterbitkan lagi.
                locked.status = AccountingEventStatus.PROCESSED
                locked.processed_at = timezone.now()

                locked.save(update_fields=[
                    "status", "processed_at", "updated_at",
                ])

                return locked

            locked.attempts += 1
            locked.status = AccountingEventStatus.PROCESSING

            locked.save(update_fields=[
                "attempts", "status", "updated_at",
            ])

        try:
            with transaction.atomic():
                return cls._generate(
                    event=locked, user=user, post=post,
                    replaces_event=replaces_event,
                )

        except ValidationError as error:
            # **Gagal dengan aman, dan gagalnya terlihat.** Kejadian
            # ditandai FAILED beserta sebabnya, jurnalnya tidak terbit
            # sebagian, dan penandanya tetap unik — jadi memperbaiki
            # kebijakannya lalu memproses ulang berjalan di baris yang
            # sama, bukan lewat kejadian kedua.
            message = "; ".join(
                f"{key}: {' '.join(str(v) for v in values)}"
                for key, values in (
                    getattr(error, "message_dict", None) or {}
                ).items()
            ) or "; ".join(error.messages)

            AccountingEvent.objects.filter(pk=locked.pk).update(
                status=AccountingEventStatus.FAILED,
                error_message=message[:4000],
            )

            logger.warning(
                "Kejadian akuntansi %s gagal diproses: %s",
                locked.idempotency_key,
                message,
            )

            locked.refresh_from_db()

            return locked

    @classmethod
    def _generate(
        cls,
        *,
        event: AccountingEvent,
        user=None,
        post=True,
        replaces_event: AccountingEvent | None = None,
    ):
        policy = AccountingPolicyService.resolve(
            event_type=event.event_type,
            company_id=event.company_id,
            on_date=event.event_date,
        )

        if policy is None:
            # **SKIPPED, bukan FAILED.** Tenant yang memang tidak
            # membukukan kejadian ini tidak punya kebijakan untuknya,
            # dan itu keadaan yang sah — bukan kesalahan yang perlu
            # ditindaklanjuti siapa pun. Membedakannya membuat layar
            # pemantauan hanya berisi baris yang benar-benar menuntut
            # perhatian.
            AccountingEvent.objects.filter(pk=event.pk).update(
                status=AccountingEventStatus.SKIPPED,
                processed_at=timezone.now(),
                error_message=(
                    f"Belum ada kebijakan akuntansi untuk "
                    f"'{event.event_type}' di perusahaan ini."
                ),
            )

            event.refresh_from_db()

            return event

        drafts = AccountingPolicyService.build_lines(
            policy=policy,
            payload=event.payload,
            company_id=event.company_id,
            on_date=event.event_date,
        )

        if not drafts:
            AccountingEvent.objects.filter(pk=event.pk).update(
                status=AccountingEventStatus.SKIPPED,
                applied_policy=policy,
                processed_at=timezone.now(),
                error_message=(
                    f"Kebijakan '{policy.code}' cocok, tapi tidak satu "
                    "aturannya pun menghasilkan baris untuk data "
                    "kejadian ini."
                ),
            )

            event.refresh_from_db()

            return event

        journal = cls._write_journal(
            event=event,
            policy=policy,
            drafts=drafts,
            user=user,
            replaces_event=replaces_event,
        )

        JournalService.assert_balanced(journal)

        # **Kebijakan yang menentukan, bukan pemanggilnya.** `post=False`
        # tetap dihormati (perintah manajemen yang sengaja menahan
        # posting), tapi kebijakan ber-`auto_post=False` tidak bisa
        # dipaksa membukukan lewat argumen — jurnalnya terbit DRAFT dan
        # masuk alur persetujuan Finance seperti jurnal manual mana pun.
        #
        # Modul sumber tidak ikut memutuskan: ia menyatakan apa yang
        # terjadi, Finance yang menentukan kapan itu masuk buku besar.
        #
        # FIN-B1/B2: lewat jalan tepercaya kebijakan, bukan `post()`
        # manual. Wewenang membukukan di sini milik konfigurasi
        # kebijakannya; aktor sumber tidak perlu — dan tidak mendapat —
        # `finance.post_journal`.
        if post and policy.auto_post:
            FinancePostingService.post_by_policy(
                journal=journal, policy=policy, user=user,
            )

        AccountingEvent.objects.filter(pk=event.pk).update(
            status=AccountingEventStatus.PROCESSED,
            applied_policy=policy,
            generated_journal=journal,
            processed_at=timezone.now(),
            error_message="",
        )

        event.refresh_from_db()

        return event

    @classmethod
    def _write_journal(
        cls, *, event, policy, drafts, user=None, replaces_event=None,
    ) -> Journal:
        period = FiscalPeriodService.open_period_for(
            company=event.company,
            posting_date=event.event_date,
            user=user,
        )

        journal = JournalService.create(
            data={
                "company": event.company,
                "journal_type": (
                    policy.journal_type or JournalType.AUTOMATIC
                ),
                "posting_date": event.event_date,
                "document_date": event.event_date,
                "accounting_period": period,
                "fiscal_year": period.fiscal_year,
                "description": (
                    f"{event.event_type} — {event.source_reference}"
                    if event.source_reference
                    else event.event_type
                ),
                # Jejak dua arah. Dari jurnal ke dokumen sumbernya lewat
                # tiga kolom ini; dari dokumen sumber ke jurnalnya lewat
                # indeks `idx_fin_journal_source`.
                "source_module": event.source_module,
                "source_type": event.source_type,
                "source_id": event.source_id,
                "source_reference": event.source_reference,
                "metadata": {
                    "accounting_event": event.pk,
                    "idempotency_key": event.idempotency_key,
                    "policy": policy.code,
                    # PF-0G. Kejadian yang digantikan jurnal ini, kalau
                    # ada. Dibaca penjaga posting
                    # (`FinancePostingService`) untuk menolak pembukuan
                    # pengganti selama ayat lama masih hidup di buku
                    # besar. Semantik Finance, bukan payroll: "kejadian
                    # ini menggantikan kejadian itu".
                    **(
                        {"replaces_event": replaces_event.pk}
                        if replaces_event is not None
                        else {}
                    ),
                },
            },
            user=user,
            # FIN-AJ1: satu-satunya pemanggil yang boleh menulis kunci
            # provenance — dan hanya untuk kejadian yang belum berjurnal.
            generating_event=event,
        )

        lines = []

        for draft in drafts:
            payload = {
                "account_id": draft.account_id,
                "debit": (
                    draft.amount if draft.side == PostingSide.DEBIT else ZERO
                ),
                "credit": (
                    draft.amount if draft.side == PostingSide.CREDIT else ZERO
                ),
                "description": draft.description,
                "source_reference": draft.source_reference,
                "metadata": draft.metadata,
                "dimensions": draft.extra_dimensions,
            }

            for code, value in draft.core_dimensions.items():
                # `company` sengaja dilewati. `JournalService._create_line`
                # sudah mengisinya dari kepala dokumen, dan mengirim
                # `company_id` di samping `company` berarti
                # `JournalLine(**data)` menerima dua cara menyebut kolom
                # yang sama — yang menang ditentukan urutan kunci, dan
                # kebijakan yang memetakan `company` ke nilai lain akan
                # menerbitkan baris milik perusahaan yang salah.
                #
                # Satu jurnal selalu milik satu perusahaan; yang boleh
                # berbeda per baris cuma unit di bawahnya.
                if code == "company":
                    continue

                payload[f"{code}_id"] = value

            lines.append(payload)

        # FIN-AJ1: jalan tepercaya pengisian proyeksi. `replace_lines()`
        # biasa menolak jurnal yang dikendalikan sumbernya — termasuk
        # yang ini, karena `metadata.accounting_event` sudah terpasang.
        JournalService.write_generated_lines(
            journal=journal, event=event, lines=lines,
        )

        journal.refresh_from_db()

        return journal

    # ------------------------------------------------------------------
    # PF-0G — pintu untuk modul sumber: penanda masuk, data biasa keluar
    # ------------------------------------------------------------------
    #
    # Modul sumber tidak boleh menyebut satu pun model Finance (dijaga
    # `test_payroll_module_names_no_finance_accounts`). Sumber yang perlu
    # tahu nasib proyeksinya — koreksi payroll harus tahu apakah jurnal
    # lamanya sudah masuk buku besar — karena itu bertanya lewat penanda
    # idempotensinya sendiri dan menerima dict berisi tipe primitif saja.
    # Nama status, kelas jurnal, dan aturan "sudah masuk buku besar"
    # tetap pengetahuan Finance.

    @classmethod
    def projection_state(cls, *, idempotency_key: str) -> dict:
        """
        Keadaan proyeksi akuntansi satu penanda, sebagai data biasa.

        `exists=False` berarti tidak ada kejadian dengan penanda itu —
        run lama/historis, atau yang kejadiannya memang tidak pernah
        dicatat. Yang memanggil harus memperlakukannya gagal tertutup.
        """
        event = (
            AccountingEvent.objects
            .filter(idempotency_key=idempotency_key)
            .select_related("generated_journal")
            .first()
        )

        if event is None:
            return {
                "exists": False, "processed": False, "superseded": False,
                "has_journal": False, "posted": False, "cancelled": False,
                "event_id": None, "journal_id": None,
            }

        journal = event.generated_journal

        return {
            "exists": True,
            "processed": event.status == AccountingEventStatus.PROCESSED,
            "superseded": event.status == AccountingEventStatus.SUPERSEDED,
            "has_journal": journal is not None,
            # "Sudah masuk buku besar" = status yang tidak bisa disunting
            # lagi, bukan sekadar POSTED — definisinya milik Finance.
            "posted": (
                journal is not None
                and journal.status in IMMUTABLE_JOURNAL_STATUSES
            ),
            "cancelled": (
                journal is not None
                and journal.status == JournalStatus.CANCELLED
            ),
            "event_id": event.pk,
            "journal_id": journal.pk if journal is not None else None,
        }

    @classmethod
    def supersede_projection_for(
        cls,
        *,
        old_key: str,
        new_event_id: int,
        user=None,
        reason: str = "",
    ) -> dict:
        """
        `supersede_unposted_projection()` untuk pemanggil yang hanya
        memegang penanda dan id — modul sumber.
        """
        old_event = AccountingEvent.objects.get(idempotency_key=old_key)
        new_event = AccountingEvent.objects.get(pk=new_event_id)

        superseded = cls.supersede_unposted_projection(
            old_event=old_event,
            new_event=new_event,
            user=user,
            reason=reason or (
                "Digantikan "
                f"{new_event.source_reference or new_event.source_id}."
            ),
        )

        return {
            "superseded_event_id": superseded.pk,
            "superseded_journal_id": superseded.generated_journal_id,
        }

    # ------------------------------------------------------------------
    # PF-0G — supersesi proyeksi yang belum diposting
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def supersede_unposted_projection(
        cls,
        *,
        old_event: AccountingEvent,
        new_event: AccountingEvent,
        user=None,
        reason: str = "",
    ) -> AccountingEvent:
        """
        Kejadian lama digantikan kejadian pengganti — **tanpa** sentuhan
        buku besar.

        Dipakai satu keadaan saja: proyeksi lama masih DRAFT (belum
        pernah masuk buku besar) dan sumbernya menerbitkan pengganti yang
        lengkap. Yang sudah diposting **tidak** lewat sini; sejarahnya
        dikoreksi lewat pembalikan Finance.

        Yang berubah cuma dua hal, dan keduanya soal keberlakuan, bukan
        isi:

        * jurnal lama → CANCELLED, dengan tautan ke kejadian pengganti;
        * kejadian lama → SUPERSEDED, dengan `superseded_by`.

        Payload, digest, penanda idempotensi, kebijakan yang dipakai, dan
        relasi `generated_journal` kejadian lama tetap apa adanya:
        jejaknya harus tetap terbaca dua tahun lagi.

        Idempoten untuk pasangan yang sama; pasangan yang berbeda ditolak.
        """
        # `select_related` sengaja **tidak** dipakai bersama
        # `select_for_update()`: `generated_journal` nullable, jadi
        # join-nya LEFT OUTER dan PostgreSQL menolak mengunci sisi yang
        # bisa NULL ("FOR UPDATE cannot be applied to the nullable side
        # of an outer join"). Barisnya dikunci sendiri, jurnalnya dibaca
        # sesudahnya.
        old = (
            AccountingEvent.objects
            .select_for_update()
            .get(pk=old_event.pk)
        )

        new = AccountingEvent.objects.get(pk=new_event.pk)

        if old.pk == new.pk:
            raise AccountingEventConflict(
                "Kejadian tidak bisa menggantikan dirinya sendiri.",
                code="supersede_self",
            )

        # Sudah dikerjakan? Pasangan yang sama diam-diam berhasil;
        # pasangan yang berbeda **gagal tertutup**.
        if old.status == AccountingEventStatus.SUPERSEDED:
            if old.superseded_by_id == new.pk:
                return old

            raise AccountingEventConflict(
                (
                    f"Kejadian #{old.pk} sudah digantikan kejadian "
                    f"#{old.superseded_by_id}."
                ),
                code="supersede_conflict",
            )

        if old.status != AccountingEventStatus.PROCESSED:
            raise AccountingEventConflict(
                (
                    f"Hanya kejadian PROCESSED yang bisa digantikan; "
                    f"#{old.pk} berstatus {old.get_status_display()}."
                ),
                code="supersede_state",
            )

        if old.company_id != new.company_id:
            raise AccountingEventConflict(
                "Kejadian pengganti harus di perusahaan yang sama.",
                code="supersede_company",
            )

        if new.status != AccountingEventStatus.PROCESSED or not new.generated_journal_id:
            raise AccountingEventConflict(
                (
                    f"Kejadian pengganti #{new.pk} belum menerbitkan "
                    "jurnalnya."
                ),
                code="supersede_replacement_missing",
            )

        if new.superseded_by_id is not None:
            raise AccountingEventConflict(
                f"Kejadian pengganti #{new.pk} sendiri sudah digantikan.",
                code="supersede_replacement_superseded",
            )

        journal = old.generated_journal

        if journal is None:
            raise AccountingEventConflict(
                f"Kejadian #{old.pk} tidak punya jurnal untuk dicabut.",
                code="supersede_without_journal",
            )

        if journal.status in IMMUTABLE_JOURNAL_STATUSES:
            raise AccountingEventConflict(
                (
                    f"Jurnal {journal.journal_number} sudah masuk buku "
                    "besar. Yang sudah diposting dikoreksi lewat "
                    "pembalikan Finance, bukan dicabut."
                ),
                code="supersede_posted_journal",
            )

        if not JournalService.is_source_controlled(journal):
            raise AccountingEventConflict(
                (
                    f"Jurnal {journal.journal_number} bukan proyeksi "
                    "kejadian akuntansi."
                ),
                code="supersede_manual_journal",
            )

        JournalService.supersede_projection(
            journal=journal, superseding_event=new, reason=reason,
        )

        AccountingEvent.objects.filter(pk=old.pk).update(
            status=AccountingEventStatus.SUPERSEDED,
            superseded_by=new,
            updated_at=timezone.now(),
        )

        old.refresh_from_db()

        return old

    # ------------------------------------------------------------------
    # FIN-AJ1 — verifikasi proyeksi
    # ------------------------------------------------------------------

    PROJECTION_DIMENSIONS = (
        "branch", "location", "division", "department", "section",
        "cost_center",
    )

    @classmethod
    def projection_signature(cls, rows) -> list[tuple]:
        """
        Isi akuntansi yang dibandingkan, dalam bentuk yang deterministik:
        `(akun, debit, kredit, dimensi inti, keterangan)` per baris,
        diurutkan. Diterima dari `DraftLine` maupun `JournalLine`.
        """
        signature = []

        for row in rows:
            if hasattr(row, "side"):
                debit = row.amount if row.side == PostingSide.DEBIT else ZERO
                credit = row.amount if row.side == PostingSide.CREDIT else ZERO
                dimensions = tuple(
                    (code, row.core_dimensions.get(code))
                    for code in cls.PROJECTION_DIMENSIONS
                )
            else:
                debit, credit = row.debit, row.credit
                dimensions = tuple(
                    (code, getattr(row, f"{code}_id"))
                    for code in cls.PROJECTION_DIMENSIONS
                )

            signature.append((
                row.account_id,
                f"{debit:.2f}",
                f"{credit:.2f}",
                dimensions,
                row.description or "",
            ))

        return sorted(signature, key=repr)

    @classmethod
    def verify_projection(cls, event: AccountingEvent) -> dict:
        """
        Apakah jurnal kejadian ini masih persis proyeksi payload-nya?

        Menyusun ulang baris dari `event.payload` dengan kebijakan yang
        **dipakai waktu itu** (`applied_policy`), lalu membandingkannya
        dengan baris jurnal yang tersimpan. Baca saja — tidak menulis apa
        pun.

        **Batasnya, dan itu nyata:** kebijakan, aturan, dan pemetaan akun
        bisa disunting sesudah jurnalnya terbit, dan tidak ada salinannya
        yang dibekukan. Hasil `False` karena itu berarti "jurnal ≠
        proyeksi dengan konfigurasi hari ini" — bisa jurnalnya yang
        berubah, bisa konfigurasinya. Yang dijamin FIN-AJ1 adalah sisi
        jurnalnya: sesudah terbit, jalur yang didukung tidak bisa
        mengubah isinya.
        """
        journal = event.generated_journal

        if journal is None or event.applied_policy is None:
            return {"verifiable": False, "matches": False, "reason": "no journal"}

        drafts = AccountingPolicyService.build_lines(
            policy=event.applied_policy,
            payload=event.payload,
            company_id=event.company_id,
            on_date=event.event_date,
        )

        expected = cls.projection_signature(drafts)
        actual = cls.projection_signature(
            journal.lines.filter(is_deleted=False),
        )

        header_ok = (
            journal.company_id == event.company_id
            and journal.posting_date == event.event_date
            and journal.source_module == event.source_module
            and journal.source_type == event.source_type
            and journal.source_id == event.source_id
            and (journal.metadata or {}).get("accounting_event") == event.pk
            and (journal.metadata or {}).get("idempotency_key")
            == event.idempotency_key
        )

        return {
            "verifiable": True,
            "matches": header_ok and expected == actual,
            "header_matches": header_ok,
            "lines_expected": len(expected),
            "lines_actual": len(actual),
        }

    # ------------------------------------------------------------------
    # Pemrosesan ulang
    # ------------------------------------------------------------------

    @classmethod
    def retry(cls, *, event: AccountingEvent, user=None) -> AccountingEvent:
        """
        Memproses ulang kejadian yang gagal atau terlewat.

        Yang sudah `PROCESSED` **tidak** diproses ulang — itu bukan
        retry, itu posting kedua. Kalau jurnalnya memang salah, yang
        benar membalik jurnalnya lalu memperbaiki kebijakannya.

        **Wewenang diperiksa di sini, bukan hanya di viewset.** Memproses
        ulang bisa menerbitkan jurnal — dan untuk kebijakan
        `auto_post=True`, memostingnya ke buku besar. Aksi `retry/`
        adalah `@action` kustom yang tidak dijaga `ModelPermission`,
        jadi sebelum ini penjagaannya cuma "sudah login + cakupan
        company".
        """
        cls.assert_may_retry(event=event, user=user)

        if event.status == AccountingEventStatus.SUPERSEDED:
            raise ValidationError({
                "status": (
                    "Kejadian ini sudah digantikan kejadian koreksi "
                    f"#{event.superseded_by_id}. Yang berlaku sekarang "
                    "jurnal penggantinya."
                ),
            })

        if event.status == AccountingEventStatus.PROCESSED:
            raise ValidationError({
                "status": (
                    f"Kejadian ini sudah menerbitkan jurnal "
                    f"{event.generated_journal.journal_number}. "
                    "Memprosesnya lagi akan membukukannya dua kali — "
                    "balik jurnalnya dulu kalau isinya salah."
                ),
            })

        AccountingEvent.objects.filter(pk=event.pk).update(
            status=AccountingEventStatus.PENDING,
            error_message="",
        )

        event.refresh_from_db()

        return cls.process(event=event, user=user)

    @staticmethod
    def assert_may_retry(*, event: AccountingEvent, user=None) -> None:
        """
        Boleh memproses ulang kejadian ini?

        Bentuknya sama dengan `PayrollRunService.assert_may_finalize` —
        izin menjawab "jenis tindakan apa", cakupan menjawab "baris milik
        siapa", dan keduanya harus ditanyakan. Cakupannya dihitung **dari
        izin retry itu sendiri**, bukan dari izin baca yang dipegang role
        lain milik orang yang sama.

        `user=None` berarti pemanggil internal tanpa konteks pengguna
        (perintah manajemen di shell server) — konvensi yang sama dengan
        Finalize payroll. Jalur API **selalu** mengirim penggunanya.
        """
        if user is None:
            return

        if not getattr(user, "is_authenticated", False):
            raise PermissionDenied(
                "Hanya pengguna yang masuk yang bisa memproses ulang "
                "kejadian akuntansi.",
            )

        if getattr(user, "is_superuser", False):
            return

        if not user.has_perm(RETRY_PERMISSION):
            raise PermissionDenied(
                "Anda tidak punya wewenang memproses ulang kejadian "
                "akuntansi.",
            )

        visible = DataScopeService.filter(
            AccountingEvent.objects.filter(pk=event.pk),
            EVENT_SCOPE,
            user,
            required_permission=RETRY_PERMISSION,
        )

        if not visible.exists():
            raise PermissionDenied(
                "Kejadian akuntansi ini berada di luar kewenangan data "
                "Anda.",
            )
