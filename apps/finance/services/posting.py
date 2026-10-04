"""
Posting engine dan pembalikan.

Dua sifat yang membedakan berkas ini dari service lain di codebase ini,
dan keduanya syarat mutlak:

* **Atomik.** Sebuah jurnal masuk buku besar seluruhnya atau tidak sama
  sekali. Tidak ada keadaan setengah terposting yang bisa dilihat siapa
  pun.
* **Idempoten.** Menekan Post dua kali, retry Celery, atau permintaan
  yang diulang jaringan tidak pernah menghasilkan dampak buku besar
  yang kedua. Yang menjaganya bukan pemeriksaan status di awal —
  itu punya jendela di antara membaca dan menulis — melainkan
  `select_for_update()` yang mengunci baris jurnalnya lebih dulu.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.finance.models import (
    IMMUTABLE_JOURNAL_STATUSES,
    Journal,
    JournalLine,
    JournalStatus,
    JournalType,
)
from apps.finance.services.account import AccountService
from apps.finance.services.authority import (
    POST_JOURNAL_PERMISSION,
    REVERSE_JOURNAL_PERMISSION,
    assert_finance_capability,
)
from apps.finance.services.fiscal import FiscalPeriodService
from apps.finance.services.journal import JournalService


# Jalan tepercaya ke `FinancePostingService._post()` — satu nilai per
# pemanggil internal yang **wewenangnya ditetapkan di tempat lain**:
#
# * `POLICY`   — kebijakan akuntansi ber-`auto_post=True`. Yang
#   mengizinkan pembukuan adalah konfigurasi kebijakannya (dijaga
#   `finance.change_accountingpolicy`), bukan aktor sumber kejadiannya.
# * `REVERSAL` — jurnal pembalik yang baru saja diterbitkan
#   `FinanceReversalService.reverse()`, yang sudah menagih
#   `finance.reverse_journal` atas jurnal aslinya.
#
# Di luar keduanya, setiap posting adalah posting **manual** dan menagih
# `finance.post_journal` + cakupan + alur persetujuan.
TRUSTED_POLICY = "policy"
TRUSTED_REVERSAL = "reversal"


@dataclass
class PostingResult:
    """
    Hasil satu permintaan posting.

    `already_posted` ada supaya pemanggil bisa membedakan "baru saja
    dibukukan" dari "sudah dibukukan sebelumnya" **tanpa** salah satunya
    berupa error. Permintaan kedua yang dibalas error akan membuat
    pemroses kejadian menandai kejadiannya gagal padahal jurnalnya
    justru sudah terbit — kegagalan palsu yang jauh lebih sulit
    ditelusuri daripada keberhasilan yang berulang.
    """

    journal: Journal
    already_posted: bool = False


class FinancePostingService:
    """Satu-satunya jalan sebuah jurnal masuk ke buku besar."""

    # Status yang **mungkin** diposting. `APPROVED` selalu; `DRAFT`
    # hanya kalau tidak ada alur persetujuan yang cocok untuk jurnalnya
    # (`_assert_workflow_allows`) — keadaan yang dinyatakan datanya
    # sendiri, bukan saklar tersendiri.
    #
    # FIN-B1/B2: `REJECTED` dikeluarkan. Jurnal yang ditolak approver
    # lalu dibukukan langsung adalah penolakan yang dibatalkan tanpa
    # jejak; jalannya sunting → ajukan ulang.
    POSTABLE_STATUSES = frozenset({
        JournalStatus.DRAFT,
        JournalStatus.APPROVED,
    })

    # ------------------------------------------------------------------
    # Posting
    # ------------------------------------------------------------------

    @classmethod
    def post(cls, *, journal: Journal, user=None) -> PostingResult:
        """
        Posting **manual** — satu-satunya pintu untuk permintaan pengguna.

        Menagih tiga hal yang terpisah, dan tidak satu pun menggantikan
        yang lain:

        1. izin `finance.post_journal`;
        2. cakupan baris jurnalnya, dihitung dari izin itu;
        3. alur persetujuan: DRAFT hanya boleh kalau tidak ada alur yang
           cocok, REJECTED tidak pernah.

        `user=None` = pemanggil tepercaya tanpa pengguna (shell, seed,
        fixture test): syarat 1–2 dilewati, syarat 3 **tidak**.
        """
        return cls._post(journal=journal, user=user, trusted=None)

    @classmethod
    def post_by_policy(cls, *, journal: Journal, policy, user=None):
        """
        Posting otomatis milik kebijakan ber-`auto_post=True`.

        Jalan tepercaya yang sempit: hanya untuk jurnal yang memang
        diterbitkan kebijakan itu (`metadata.policy`), dan hanya selama
        kebijakannya memang meminta posting. Aktor sumber (`user`) tetap
        dicatat sebagai `posted_by` dan tetap tunduk pada periode
        SOFT_CLOSED, tapi ia **tidak** perlu `finance.post_journal` —
        yang mengizinkan adalah kebijakannya, bukan dia.
        """
        if not getattr(policy, "auto_post", False):
            raise ValidationError({
                "policy": (
                    f"Kebijakan '{policy.code}' tidak meminta posting "
                    "otomatis."
                ),
            })

        if (journal.metadata or {}).get("policy") != policy.code:
            raise ValidationError({
                "journal": (
                    f"Jurnal {journal.journal_number} tidak diterbitkan "
                    f"kebijakan '{policy.code}'."
                ),
            })

        return cls._post(journal=journal, user=user, trusted=TRUSTED_POLICY)

    @classmethod
    def assert_may_post(cls, *, journal: Journal, user=None) -> None:
        """Izin `finance.post_journal` + cakupan dari izin itu."""
        JournalService.assert_may(
            journal=journal,
            user=user,
            permission=POST_JOURNAL_PERMISSION,
            action="memposting jurnal",
        )

    @classmethod
    @transaction.atomic
    def _post(cls, *, journal: Journal, user=None, trusted=None) -> PostingResult:
        # **Kunci dulu, baca kemudian.** Memeriksa status dari objek
        # yang sudah di tangan lalu menulis sesudahnya punya jendela di
        # antaranya: dua permintaan bersamaan sama-sama melihat
        # APPROVED, dan keduanya memposting. Yang kedua kemudian ditolak
        # constraint nomor — kalau ada — atau tidak ditolak sama sekali
        # dan buku besarnya menerima dampak dua kali.
        locked = (
            Journal.objects
            .select_for_update()
            .select_related(
                "company",
                "fiscal_year",
                "accounting_period",
                "currency",
                "base_currency",
            )
            .get(pk=journal.pk)
        )

        # Wewenang **sebelum** apa pun — termasuk sebelum jawaban
        # "sudah diposting", supaya yang tidak berwenang bahkan tidak
        # mendapat keadaan dokumennya.
        if trusted is None:
            cls.assert_may_post(journal=locked, user=user)

        if locked.status in IMMUTABLE_JOURNAL_STATUSES:
            # Bukan error. Lihat `PostingResult.already_posted`.
            return PostingResult(journal=locked, already_posted=True)

        if trusted is None:
            cls._assert_workflow_allows(journal=locked)
            cls._assert_predecessor_settled(journal=locked)

        cls._validate(journal=locked, user=user)

        now = timezone.now()

        locked.status = JournalStatus.POSTED
        locked.posted_at = now
        locked.posted_by = user

        locked.save(update_fields=[
            "status", "posted_at", "posted_by", "updated_at",
        ])

        cls._stamp_lines(locked)

        return PostingResult(journal=locked, already_posted=False)

    @staticmethod
    def _assert_workflow_allows(*, journal: Journal) -> None:
        """
        Posting manual tidak boleh melompati alur persetujuan.

        `APPROVED` sudah melewatinya. `DRAFT` hanya kalau **tidak ada**
        alur yang cocok untuk jurnal ini — pencocoknya resolver yang sama
        yang dipakai `JournalService.submit()`, jadi "wajib disetujui"
        tidak bisa punya dua jawaban. Selebihnya ditolak.
        """
        if journal.status == JournalStatus.APPROVED:
            return

        if journal.status == JournalStatus.DRAFT:
            definition = JournalService._find_definition(journal)

            if definition is None:
                return

            raise ValidationError({
                "status": (
                    f"Jurnal {journal.journal_number} wajib disetujui "
                    f"lewat alur '{definition.code}' sebelum diposting. "
                    "Ajukan (Submit) dulu."
                ),
            })

        raise ValidationError({
            "status": (
                f"Jurnal berstatus {journal.get_status_display()} tidak "
                "bisa diposting."
            ),
        })

    @staticmethod
    def _assert_predecessor_settled(*, journal: Journal) -> None:
        """
        PF-0G — pengganti tidak masuk buku besar selagi ayat lama hidup.

        Jurnal yang diterbitkan kejadian pengganti membawa
        `metadata.replaces_event`. Kalau jurnal kejadian yang digantikan
        masih POSTED (belum dibalik Finance), memposting penggantinya
        berarti dampak yang sama terbukukan dua kali — dan yang kedua
        terlihat sah.

        Pembalikannya **tidak** dijalankan di sini: membalik ayat yang
        sudah terbit adalah wewenang Finance tersendiri
        (`finance.reverse_journal`), bukan efek samping posting.
        """
        replaced = (journal.metadata or {}).get("replaces_event")

        if not replaced:
            return

        from apps.finance.models import AccountingEvent

        predecessor = (
            AccountingEvent.objects
            .filter(pk=replaced)
            .select_related("generated_journal")
            .first()
        )

        old_journal = getattr(predecessor, "generated_journal", None)

        if old_journal is None:
            return

        if old_journal.status != JournalStatus.POSTED:
            # DRAFT/CANCELLED (sudah digantikan) atau REVERSED — ayat
            # lamanya tidak lagi hidup di buku besar.
            return

        raise ValidationError({
            "correction_predecessor_not_reversed": (
                f"Jurnal {journal.journal_number} menggantikan "
                f"{old_journal.journal_number}, yang masih terposting. "
                "Balik dulu jurnal lamanya (Reverse) — tanpa itu dampak "
                "yang sama masuk buku besar dua kali."
            ),
        })

    @classmethod
    def _validate(cls, *, journal: Journal, user=None) -> None:
        """
        Seluruh syarat yang harus benar sebelum sebuah jurnal jadi fakta.

        Diperiksa **di sini**, bukan hanya di serializer: importer,
        seed, pemroses kejadian akuntansi, dan perintah manajemen
        semuanya melewati posting engine dan tidak satu pun melewati
        serializer.
        """
        if journal.status not in cls.POSTABLE_STATUSES:
            raise ValidationError({
                "status": (
                    f"Jurnal berstatus {journal.get_status_display()} "
                    "tidak bisa diposting."
                ),
            })

        lines = list(
            JournalLine.objects
            .filter(journal=journal, is_deleted=False)
            .select_related("account", "transaction_currency")
        )

        if not lines:
            raise ValidationError({
                "lines": "Jurnal tanpa baris tidak bisa diposting.",
            })

        # Keseimbangan, pada kedua mata uang.
        JournalService.assert_balanced(journal)

        # Kalender akuntansi. Tahun bukunya, lalu periodenya — dan
        # periodenya diperiksa ulang terhadap tanggal posting, bukan
        # dipercaya dari kolomnya: tanggal boleh berubah sesudah periode
        # dipilih, dan jurnal yang periodenya tidak lagi memuat
        # tanggalnya akan mendarat di bulan yang salah di seluruh
        # laporan.
        FiscalPeriodService.assert_year_open(fiscal_year=journal.fiscal_year)

        period = journal.accounting_period

        if not period.contains(journal.posting_date):
            raise ValidationError({
                "posting_date": (
                    f"Tanggal pembukuan {journal.posting_date} berada di "
                    f"luar periode '{period.code}' ({period.start_date} "
                    f"– {period.end_date})."
                ),
            })

        FiscalPeriodService.assert_postable(period=period, user=user)

        # Akun: aktif, boleh diposting, dan milik perusahaan yang benar.
        for line in lines:
            AccountService.assert_postable(
                line.account,
                company_id=journal.company_id,
            )

        cls._assert_required_dimensions(journal=journal, lines=lines)

        # Cakupan data pembukunya. Diperiksa terakhir supaya penolakan
        # karena data yang salah — yang bisa diperbaiki pemakainya —
        # muncul lebih dulu daripada penolakan karena wewenang, yang
        # tidak bisa.
        JournalService.assert_within_scope(journal=journal, user=user)

    @staticmethod
    def _assert_required_dimensions(*, journal: Journal, lines) -> None:
        """
        Dimensi yang dinyatakan wajib harus terisi di setiap baris.

        Dimensi inti dibaca dari kolom barisnya; dimensi tambahan dari
        baris `JournalLineDimension`. Diperiksa saat **posting**, bukan
        saat menyimpan draf: kewajiban dimensi adalah aturan pelaporan,
        dan draf yang belum lengkap harus tetap bisa disimpan sambil
        datanya dicari.
        """
        from apps.finance.models import CORE_DIMENSIONS, AccountingDimension

        required = list(
            AccountingDimension.objects.filter(
                is_required=True,
                is_deleted=False,
                is_active=True,
            )
        )

        if not required:
            return

        extra_by_line: dict[int, set[str]] = {}

        extra_codes = [
            row.code for row in required if row.code not in CORE_DIMENSIONS
        ]

        if extra_codes:
            from apps.finance.models import JournalLineDimension

            rows = (
                JournalLineDimension.objects
                .filter(
                    journal_line__journal=journal,
                    dimension_code__in=extra_codes,
                    is_deleted=False,
                )
                .values_list("journal_line_id", "dimension_code")
            )

            for line_id, code in rows:
                extra_by_line.setdefault(line_id, set()).add(code)

        missing: list[str] = []

        for line in lines:
            for dimension in required:
                code = dimension.code

                if code in CORE_DIMENSIONS:
                    filled = getattr(line, f"{code}_id", None) is not None
                else:
                    filled = code in extra_by_line.get(line.pk, set())

                if not filled:
                    missing.append(
                        f"baris {line.line_number}: {dimension.name}"
                    )

        if missing:
            raise ValidationError({
                "lines": (
                    "Dimensi wajib belum terisi — "
                    + "; ".join(missing[:10])
                    + ("…" if len(missing) > 10 else "")
                ),
            })

    @staticmethod
    def _stamp_lines(journal: Journal) -> int:
        """
        Menyalin penyaring buku besar ke barisnya.

        Satu `UPDATE` untuk seluruh baris, di dalam transaksi posting
        yang sama — jadi tidak pernah ada baris yang bertanda terposting
        sementara kepalanya belum, atau sebaliknya.

        Yang disalin **hanya penyaring**: tanggal, periode, dan
        penanda. Tidak satu angka pun — nilai debit dan kredit tetap
        tinggal di barisnya sendiri dan tidak pernah diringkas ke mana
        pun. Itu yang membuat kolom-kolom ini turunan yang bisa
        dibangun ulang, bukan saldo yang bisa menyimpang.
        """
        return (
            JournalLine.objects
            .filter(journal=journal)
            .update(
                posting_date=journal.posting_date,
                accounting_period_id=journal.accounting_period_id,
                is_posted=True,
            )
        )

    # ------------------------------------------------------------------
    # Posting massal
    # ------------------------------------------------------------------

    @classmethod
    def post_many(cls, *, journals, user=None) -> dict:
        """
        Memposting beberapa jurnal, **satu transaksi per jurnal**.

        Sengaja bukan satu transaksi untuk semuanya: satu jurnal yang
        periodenya tertutup tidak boleh membatalkan dua ratus jurnal
        lain yang sudah sah. Yang gagal dilaporkan beserta sebabnya,
        yang berhasil tetap masuk.
        """
        from rest_framework.exceptions import PermissionDenied

        # Izinnya ditagih sekali **sebelum** jurnal pertama: tanpa
        # `finance.post_journal` tidak ada satu jurnal pun yang boleh
        # tersentuh, bukan "sebagian gagal". Cakupan per jurnal tetap
        # dinilai `post()` untuk masing-masing.
        assert_finance_capability(
            user=user,
            permission=POST_JOURNAL_PERMISSION,
            action="memposting jurnal",
        )

        posted = 0
        skipped = 0
        failed: list[dict] = []

        for journal in journals:
            try:
                result = cls.post(journal=journal, user=user)
            except ValidationError as error:
                failed.append({
                    "journal": journal.journal_number or journal.pk,
                    "errors": getattr(error, "message_dict", None)
                    or {"detail": list(error.messages)},
                })

                continue
            except PermissionDenied as error:
                failed.append({
                    "journal": journal.journal_number or journal.pk,
                    "errors": {"detail": [str(error.detail)]},
                })

                continue

            if result.already_posted:
                skipped += 1
            else:
                posted += 1

        return {
            "posted": posted,
            "already_posted": skipped,
            "failed": failed,
            "requested": posted + skipped + len(failed),
        }


class FinanceReversalService:
    """
    Pembalikan jurnal.

    Jurnal asli **tidak disentuh** selain ditandai sudah dibalik. Yang
    lahir adalah dokumen baru berisi ayat yang berlawanan, dan keduanya
    saling menunjuk. Itu yang membuat pertanyaan "kenapa angka ini
    berubah" punya jawaban yang bisa dibaca dua tahun lagi.
    """

    @classmethod
    @transaction.atomic
    def reverse(
        cls,
        *,
        journal: Journal,
        user=None,
        posting_date: date | None = None,
        reason: str = "",
        post: bool = True,
    ) -> Journal:
        original = (
            Journal.objects
            .select_for_update()
            .select_related("company", "currency", "base_currency")
            .get(pk=journal.pk)
        )

        # FIN-B1/B2. Membalik = menerbitkan **dan** memposting jurnal
        # baru, jadi wewenangnya sendiri: `finance.reverse_journal` +
        # cakupan jurnal aslinya dari izin itu.
        JournalService.assert_may(
            journal=original,
            user=user,
            permission=REVERSE_JOURNAL_PERMISSION,
            action="membalik jurnal",
        )

        if original.status != JournalStatus.POSTED:
            raise ValidationError({
                "status": (
                    "Hanya jurnal yang sudah diposting yang bisa "
                    "dibalik. Yang masih draf cukup disunting atau "
                    "dibatalkan."
                ),
            })

        if original.reversed_by_id:
            raise ValidationError({
                "status": (
                    f"Jurnal {original.journal_number} sudah dibalik "
                    f"oleh {original.reversed_by.journal_number}. "
                    "Membalik dua kali akan membukukan ayatnya kembali "
                    "seperti semula."
                ),
            })

        if not reason.strip():
            raise ValidationError({
                "reason": (
                    "Sebutkan alasan pembalikan. Jurnal pembalik tanpa "
                    "alasan menghasilkan dua ayat yang saling meniadakan "
                    "dan tidak seorang pun tahu kenapa keduanya ada."
                ),
            })

        # Tanggal pembalikan boleh berbeda dari aslinya, dan lazimnya
        # memang berbeda: kesalahan bulan lalu yang ketahuan bulan ini
        # dibalik di bulan ini kalau periode lamanya sudah ditutup.
        # Bawaannya tanggal asli — itu yang benar selama periodenya
        # masih terbuka, karena laporan bulan itu jadi bersih dengan
        # sendirinya.
        posting_date = posting_date or original.posting_date

        period = FiscalPeriodService.open_period_for(
            company=original.company,
            posting_date=posting_date,
            user=user,
        )

        reversal = JournalService.create(
            data={
                "company": original.company,
                "journal_type": JournalType.REVERSAL,
                "posting_date": posting_date,
                "document_date": original.document_date,
                "accounting_period": period,
                "fiscal_year": period.fiscal_year,
                "currency": original.currency,
                "base_currency": original.base_currency,
                "exchange_rate": original.exchange_rate,
                "description": (
                    f"Reversal of {original.journal_number} — {reason}"
                ),
                "status_reason": reason,
                "reversal_of": original,
                # Jejak ke dokumen sumber ikut disalin, jadi penelusuran
                # dari slip gaji ke jurnalnya menemukan **keduanya** —
                # yang asli dan pembaliknya. Tanpa itu, dokumen sumber
                # terlihat masih membawa dampak yang sebenarnya sudah
                # dicabut.
                "source_module": original.source_module,
                "source_type": original.source_type,
                "source_id": original.source_id,
                "source_reference": original.source_reference,
                "metadata": {
                    "reversal_of": original.journal_number,
                    "reason": reason,
                },
            },
            user=user,
        )

        cls._copy_inverted_lines(original=original, reversal=reversal)

        JournalService.sync_totals(reversal)

        original.reversed_by = reversal
        original.reversed_at = timezone.now()
        original.reversed_by_user = user
        original.status = JournalStatus.REVERSED

        original.save(update_fields=[
            "reversed_by", "reversed_at", "reversed_by_user",
            "status", "updated_at",
        ])

        if post:
            # Jalan tepercaya: wewenangnya barusan ditagih di atas
            # (`reverse_journal`), dan pembalik ayat yang sudah disetujui
            # tidak masuk alur persetujuan kedua kalinya.
            FinancePostingService._post(
                journal=reversal,
                user=user,
                trusted=TRUSTED_REVERSAL,
            )

            reversal.refresh_from_db()

        return reversal

    @staticmethod
    def _copy_inverted_lines(*, original: Journal, reversal: Journal) -> None:
        """
        Menyalin barisnya dengan debit dan kredit ditukar.

        Dimensi ikut apa adanya — pembalik harus mendarat di unit biaya
        yang sama dengan yang dibebani, kalau tidak yang terjadi bukan
        pembalikan melainkan pemindahan biaya antarunit.
        """
        from apps.finance.models import JournalLineDimension

        source_lines = list(
            original.lines
            .filter(is_deleted=False)
            .prefetch_related("dimension_values")
            .order_by("line_number")
        )

        for line in source_lines:
            copy = JournalLine(
                journal=reversal,
                line_number=line.line_number,
                account=line.account,
                # Ditukar. Inilah seluruh isi "pembalikan".
                debit=line.credit,
                credit=line.debit,
                base_debit=line.base_credit,
                base_credit=line.base_debit,
                transaction_currency=line.transaction_currency,
                exchange_rate=line.exchange_rate,
                description=(
                    f"Reversal — {line.description}"
                    if line.description
                    else "Reversal"
                ),
                company=line.company,
                branch=line.branch,
                location=line.location,
                division=line.division,
                department=line.department,
                section=line.section,
                cost_center=line.cost_center,
                source_reference=line.source_reference,
                reconciliation_reference=line.reconciliation_reference,
                metadata={"reversal_of_line": line.pk},
            )

            copy.full_clean()
            copy.save()

            values = [
                JournalLineDimension(
                    journal_line=copy,
                    dimension_id=value.dimension_id,
                    dimension_code=value.dimension_code,
                    value_id=value.value_id,
                    value_text=value.value_text,
                    value_label=value.value_label,
                )
                for value in line.dimension_values.filter(is_deleted=False)
            ]

            if values:
                JournalLineDimension.objects.bulk_create(values)
