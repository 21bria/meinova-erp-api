"""
Service jurnal: pembuatan, penyuntingan, pengajuan, dan pembatalan.

Yang **tidak** ada di sini: posting dan pembalikan. Keduanya di
`posting.py`, dan pemisahannya disengaja — menyunting draf dan
membukukan fakta akuntansi adalah dua tanggung jawab dengan aturan yang
sama sekali berbeda, dan menyatukannya membuat setiap perubahan pada
jalur draf harus dibaca ulang terhadap jalur posting.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.scoping import DataScopeService
from apps.administration.api.numbering.services.numbering_service import (
    DocumentNumberService,
)
from apps.core.services.master import BaseMasterService
from apps.finance.models import (
    EDITABLE_JOURNAL_STATUSES,
    IMMUTABLE_JOURNAL_STATUSES,
    ZERO,
    AccountingDimension,
    Journal,
    JournalLine,
    JournalLineDimension,
    JournalStatus,
)
from apps.finance.services.account import AccountService
from apps.finance.services.authority import (
    CHANGE_JOURNAL_PERMISSION,
    assert_finance_action,
)
from apps.finance.services.fiscal import FiscalPeriodService


WORKFLOW_MODULE = "finance"
WORKFLOW_DOCUMENT_TYPE = "journal"

NUMBERING_MODULE = "finance"
NUMBERING_DOCUMENT_TYPE = "journal"


# Peta cakupan data untuk jurnal. Dipakai viewset **dan** pemeriksaan
# jalur tulis — satu deklarasi, dua pemakai. Dua salinan yang harus
# tetap sama adalah cara membuat jalur tulis melebar tanpa jalur baca
# ikut melebar, dan itu persis lubang yang dua kali ditemukan di modul
# HR.
JOURNAL_SCOPE = {
    "company": "company",
    "branch": "lines__branch",
    "location": "lines__location",
    "division": "lines__division",
    "department": "lines__department",
    "section": "lines__section",
    "cost_center": "lines__cost_center",
}


# FIN-AJ1. Kunci metadata yang hanya boleh ditulis pemroses kejadian
# akuntansi. Jurnal yang membawanya — atau yang ditunjuk
# `AccountingEvent.generated_journal` — adalah **proyeksi** kejadiannya,
# dan isinya dikendalikan sumbernya, bukan layar jurnal.
PROVENANCE_METADATA_KEYS = (
    "accounting_event",
    "idempotency_key",
    "policy",
    # PF-0G — ditulis pemroses (`replaces_event`) dan layanan supersesi
    # (`superseded_by_event`). Keduanya dibaca penjaga posting, jadi
    # keduanya harus mustahil diketik dari form jurnal.
    "replaces_event",
    "superseded_by_event",
)

AUTOMATIC_JOURNAL_ERROR_CODE = "automatic_journal_source_controlled"


class AutomaticJournalLocked(ValidationError):
    """
    Penyuntingan/pembatalan jurnal yang dikendalikan sumbernya.

    Bentuknya konvensi yang sama dengan `PayrollAccountingError` dan
    `AccountingEventError`: satu kunci tetap (`automatic_journal`) di
    `errors` API, plus `error_code` untuk pemanggil service. Pesannya
    hanya menyebut nomor jurnal dan nomor kejadian — tidak ada angka,
    tidak ada nama.
    """

    def __init__(self, journal: Journal, *, action: str):
        event = (journal.metadata or {}).get("accounting_event")

        super().__init__(
            {
                "automatic_journal": [
                    f"Jurnal {journal.journal_number or journal.pk} "
                    "diterbitkan dari kejadian akuntansi"
                    f"{f' #{event}' if event else ''} dan isinya dikendalikan "
                    f"sumbernya — tidak bisa {action} dari sini. Koreksinya "
                    "lewat dokumen/kejadian sumbernya, atau Reverse kalau "
                    "sudah diposting.",
                ],
            },
            code=AUTOMATIC_JOURNAL_ERROR_CODE,
        )

        self.error_code = AUTOMATIC_JOURNAL_ERROR_CODE


class JournalService(BaseMasterService):
    model = Journal

    WORKFLOW_MODULE = WORKFLOW_MODULE
    WORKFLOW_DOCUMENT_TYPE = WORKFLOW_DOCUMENT_TYPE

    @staticmethod
    def list():
        return (
            Journal.objects
            .filter(is_deleted=False)
            .select_related(
                "company",
                "fiscal_year",
                "accounting_period",
                "currency",
                "base_currency",
                "reversal_of",
                "reversed_by",
                "posted_by",
            )
            .order_by("-posting_date", "-id")
        )

    # ------------------------------------------------------------------
    # Penyusunan
    # ------------------------------------------------------------------

    @classmethod
    def prepare_create_data(cls, *, data: dict[str, Any], user=None, **kwargs):
        cls._assert_provenance_claim(
            data, generating_event=kwargs.get("generating_event"),
        )

        data = cls._apply_period(data)
        data = cls._apply_currency(data)
        data = cls._apply_number(data)

        return data

    @classmethod
    def prepare_update_data(cls, *, instance, data, user=None, **kwargs):
        cls.assert_content_mutable(instance, action="disunting")
        cls._assert_provenance_claim(data, generating_event=None)

        merged = {**cls._current_values(instance), **data}

        data = cls._apply_period(merged, instance=instance, changed=data)
        data = cls._apply_currency(data, instance=instance)

        # Nomor tidak pernah ditulis ulang. Nomor dokumen yang berubah
        # sesudah disebut di email atau dicetak adalah nomor yang tidak
        # bisa dipakai merujuk apa pun.
        data.pop("journal_number", None)

        return data

    @staticmethod
    def _current_values(instance: Journal) -> dict:
        """
        Nilai yang harus ikut dipertimbangkan setiap kali dokumen
        disunting, walau tidak dikirim.

        **Kelimanya, bukan tiga.** `_apply_currency()` menolak jurnal
        bermata uang asing yang tidak menyebutkan kursnya — jadi kalau
        `exchange_rate` dan `base_currency` tidak ikut di sini, PATCH
        yang cuma mengubah keterangan akan ditolak dengan "Jurnal dalam
        mata uang asing harus menyebutkan kursnya". Dokumen valas jadi
        tidak bisa disunting sama sekali, dan pesannya menunjuk kolom
        yang si penyunting tidak pernah sentuh.
        """
        return {
            "company": instance.company,
            "posting_date": instance.posting_date,
            "currency": instance.currency,
            "exchange_rate": instance.exchange_rate,
            "base_currency": instance.base_currency,
        }

    @classmethod
    def _apply_period(cls, data: dict, *, instance=None, changed=None) -> dict:
        """
        Menurunkan periode dan tahun buku dari tanggal pembukuan.

        **Diturunkan, bukan diminta.** Tanggal yang tidak cocok dengan
        periode yang dipilih adalah kesalahan yang paling gampang
        dibuat, dan `Journal.clean()` memang menolaknya — tapi menolak
        sesuatu yang bisa dihitung sendiri cuma memindahkan pekerjaan ke
        orang. Periode yang dikirim klien tetap dihormati kalau memang
        cocok; yang diganti hanya yang tidak diisi atau yang tidak
        memuat tanggalnya.
        """
        company = data.get("company")
        posting_date = data.get("posting_date")

        if company is None or posting_date is None:
            return data

        period = data.get("accounting_period")

        if period is not None and period.contains(posting_date):
            data["fiscal_year"] = period.fiscal_year

            return data

        resolved = FiscalPeriodService.resolve(
            company=company,
            posting_date=posting_date,
        )

        data["accounting_period"] = resolved
        data["fiscal_year"] = resolved.fiscal_year

        return data

    @classmethod
    def _apply_currency(cls, data: dict, *, instance=None) -> dict:
        """
        Mata uang buku besar diambil dari master, bukan diketik.

        Yang boleh diketik mata uang **transaksi**. Mata uang pelaporan
        adalah sifat perusahaan, dan membiarkannya dipilih per dokumen
        berarti satu perusahaan bisa punya buku besar dalam dua mata
        uang tanpa ada yang menyadarinya sampai neracanya disusun.
        """
        from apps.administration.models import Currency

        if data.get("base_currency") is None:
            base = (
                Currency.objects
                .filter(is_base_currency=True, is_deleted=False)
                .order_by("pk")
                .first()
            )

            if base is None:
                raise ValidationError({
                    "base_currency": (
                        "Belum ada mata uang yang ditandai sebagai mata "
                        "uang dasar. Tandai satu di Administration → "
                        "Currency sebelum membuat jurnal."
                    ),
                })

            data["base_currency"] = base

        if data.get("currency") is None:
            data["currency"] = data["base_currency"]

        # Kurs 1 untuk jurnal yang mata uangnya memang mata uang buku.
        # Tidak dibaca dari tabel kurs: kurs sebuah mata uang terhadap
        # dirinya sendiri tidak pernah selain satu, dan membacanya dari
        # tabel membuat jurnal rupiah gagal terbit di tenant yang belum
        # mengisi kurs sama sekali.
        if data.get("currency") == data.get("base_currency"):
            data["exchange_rate"] = Decimal("1.000000")

        elif not data.get("exchange_rate"):
            raise ValidationError({
                "exchange_rate": (
                    "Jurnal dalam mata uang asing harus menyebutkan "
                    "kursnya terhadap mata uang buku besar."
                ),
            })

        return data

    @classmethod
    def _apply_number(cls, data: dict) -> dict:
        if data.get("journal_number"):
            return data

        data["journal_number"] = DocumentNumberService.next(
            module=NUMBERING_MODULE,
            document_type=NUMBERING_DOCUMENT_TYPE,
            company=data.get("company"),
            when=data.get("posting_date"),
        )

        return data

    # ------------------------------------------------------------------
    # Keadaan dokumen
    # ------------------------------------------------------------------

    @staticmethod
    def assert_editable(journal: Journal) -> None:
        """
        Satu-satunya gerbang penyuntingan, dipakai seluruh jalur tulis.

        Jurnal yang sudah diposting ditolak dengan kalimat yang
        menyebut **jalan keluarnya**, bukan cuma penolakannya: orang
        yang menemukan angka salah di jurnal yang sudah dibukukan perlu
        tahu bahwa yang harus ia lakukan membalik, bukan mencari tombol
        edit yang lebih tersembunyi.

        **Statusnya dibaca ulang dari database, bukan dari objek yang
        dioper.** Itu satu query berindeks pk, dan ia menutup satu kelas
        bug seluruhnya: `FinancePostingService.post()` bekerja pada
        baris yang dikunci sendiri, jadi objek yang dipegang pemanggil
        tetap berkata `draft` sesudah jurnalnya benar-benar diposting.
        Setiap pemanggil yang lupa `refresh_from_db()` akan lolos dari
        gerbang ini — dan yang lolos adalah penyuntingan fakta akuntansi
        yang sudah masuk buku besar.

        Immutability adalah aturan yang tidak boleh bergantung pada
        kedisiplinan pemanggilnya.
        """
        status = (
            Journal.objects
            .filter(pk=journal.pk)
            .values_list("status", flat=True)
            .first()
            if journal.pk
            else journal.status
        ) or journal.status

        if status != journal.status:
            # Objeknya basi. Disegarkan supaya pesan kesalahan menyebut
            # keadaan yang sebenarnya, bukan keadaan yang sudah lewat.
            journal.status = status

        if status in IMMUTABLE_JOURNAL_STATUSES:
            raise ValidationError({
                "status": (
                    f"Jurnal {journal.journal_number} sudah diposting "
                    "dan tidak bisa diubah maupun dihapus. Koreksinya "
                    "lewat Reverse — jurnal pembalik yang menunjuk "
                    "dokumen ini — lalu terbitkan jurnal yang benar."
                ),
            })

        if status not in EDITABLE_JOURNAL_STATUSES:
            raise ValidationError({
                "status": (
                    f"Jurnal {journal.journal_number} berstatus "
                    f"{journal.get_status_display()} dan tidak bisa "
                    "diubah. Tarik kembali pengajuannya dulu."
                ),
            })

    # ------------------------------------------------------------------
    # FIN-AJ1 — jurnal yang dikendalikan sumbernya
    # ------------------------------------------------------------------

    @staticmethod
    def is_source_controlled(journal: Journal) -> bool:
        """
        Apakah jurnal ini proyeksi sebuah kejadian akuntansi?

        Dua tanda, dan **salah satu cukup** — gagal tertutup:

        * `metadata.accounting_event` pada baris jurnal **yang tersimpan**
          (dibaca ulang dari database, bukan dari objek yang dioper —
          objek yang dioper bisa sudah diubah pemanggilnya);
        * `AccountingEvent.generated_journal` yang menunjuk jurnal ini —
          relasi yang ditulis pemroses kejadian dan tidak punya jalur
          tulis dari API.

        **Bukan** `journal_type`: jenis `automatic` bisa dipilih di form
        jurnal manual, jadi ia tidak membuktikan asal apa pun.
        """
        from apps.finance.models import AccountingEvent

        if not journal.pk:
            return bool((journal.metadata or {}).get("accounting_event"))

        stored = (
            Journal.objects
            .filter(pk=journal.pk)
            .values_list("metadata", flat=True)
            .first()
        ) or {}

        if stored.get("accounting_event") not in (None, ""):
            return True

        return AccountingEvent.objects.filter(
            generated_journal_id=journal.pk,
        ).exists()

    @classmethod
    def assert_content_mutable(cls, journal: Journal, *, action: str = "diubah"):
        """
        Gerbang **isi** dokumen: kepala, baris, dimensi, penghapusan.

        `assert_editable` menjawab "statusnya masih draf?"; yang di sini
        menambah "dan isinya memang milik layar jurnal?". Jurnal yang
        dikendalikan sumbernya ditolak di **setiap** status — DRAFT,
        REJECTED sesudah ditolak, DRAFT sesudah ditarik — dan izin apa
        pun tidak membukanya: ini aturan integritas, bukan wewenang.

        Perpindahan status (ajukan, tarik, setujui, posting, balik)
        **tidak** lewat sini; jurnal otomatis tetap menempuh alur Finance
        biasa.
        """
        if cls.is_source_controlled(journal):
            journal.metadata = (
                Journal.objects
                .filter(pk=journal.pk)
                .values_list("metadata", flat=True)
                .first()
                if journal.pk
                else journal.metadata
            ) or {}

            raise AutomaticJournalLocked(journal, action=action)

        cls.assert_editable(journal)

    @staticmethod
    def _assert_provenance_claim(data: dict, *, generating_event=None) -> None:
        """
        Kunci provenance di `metadata` hanya boleh ditulis pemroses
        kejadian — dan hanya untuk kejadian yang memang sedang menerbitkan
        jurnal pertamanya.

        Tanpa ini, form jurnal manual bisa mengaku sebagai proyeksi
        kejadian mana pun (metadata adalah kolom JSON yang bisa diisi),
        atau pemanggil service bisa menerbitkan jurnal kedua untuk
        kejadian yang sudah punya jurnal.
        """
        metadata = data.get("metadata") or {}

        claimed = [key for key in PROVENANCE_METADATA_KEYS if key in metadata]

        if not claimed:
            return

        from apps.finance.models import AccountingEvent

        event_id = metadata.get("accounting_event")

        valid = (
            generating_event is not None
            and event_id == generating_event.pk
            and not (
                AccountingEvent.objects
                .filter(pk=generating_event.pk)
                .exclude(generated_journal__isnull=True)
                .exists()
            )
        )

        if not valid:
            raise ValidationError({
                "metadata": (
                    f"Kunci {', '.join(claimed)} hanya ditulis pemroses "
                    "kejadian akuntansi saat menerbitkan jurnalnya."
                ),
            })

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        cls.assert_content_mutable(instance, action="dihapus")

    # ------------------------------------------------------------------
    # Baris
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def replace_lines(
        cls,
        *,
        journal: Journal,
        lines: list[dict],
        user=None,
    ) -> Journal:
        """
        Mengganti seluruh baris jurnal.

        Diganti utuh, bukan ditambal per baris: jurnal adalah satu ayat
        yang harus seimbang, dan menyunting barisnya satu per satu
        membuat dokumen melewati keadaan-keadaan yang tidak seimbang
        yang masing-masing harus diputuskan sah atau tidak. Mengganti
        seluruhnya lalu menyeimbangkan sekali jauh lebih mudah dibaca —
        dan itu juga bentuk yang dikirim form.
        """
        cls.assert_content_mutable(journal, action="diganti barisnya")

        return cls._write_lines(journal=journal, lines=lines)

    @classmethod
    @transaction.atomic
    def write_generated_lines(
        cls,
        *,
        journal: Journal,
        event,
        lines: list[dict],
    ) -> Journal:
        """
        Jalan tepercaya **satu-satunya** untuk mengisi jurnal proyeksi.

        Dipanggil `AccountingEventProcessor._generate()` tepat sesudah
        jurnalnya dibuat. Sempit dengan sengaja — ia hanya mau menulis
        kalau:

        * jurnalnya milik kejadian itu (`metadata.accounting_event`);
        * kejadiannya belum menunjuk jurnal mana pun;
        * jurnalnya DRAFT dan **belum pernah** punya baris (termasuk yang
          terhapus).

        Jadi ia tidak bisa dipakai menulis ulang proyeksi yang sudah
        terbit: sekali ada baris, pintunya tertutup.
        """
        from apps.finance.models import AccountingEvent

        locked = Journal.objects.select_for_update().get(pk=journal.pk)

        # `JournalLine.objects` tidak menyaring `is_deleted`, jadi baris
        # yang pernah ada — terhapus atau tidak — ikut menutup pintunya.
        already_filled = JournalLine.objects.filter(journal=locked).exists()

        already_linked = AccountingEvent.objects.filter(
            pk=event.pk,
        ).exclude(generated_journal__isnull=True).exists()

        if (
            (locked.metadata or {}).get("accounting_event") != event.pk
            or locked.status != JournalStatus.DRAFT
            or already_filled
            or already_linked
        ):
            raise AutomaticJournalLocked(locked, action="diisi ulang")

        return cls._write_lines(journal=journal, lines=lines)

    @classmethod
    @transaction.atomic
    def supersede_projection(
        cls,
        *,
        journal: Journal,
        superseding_event,
        reason: str = "",
    ) -> Journal:
        """
        PF-0G — mencabut keberlakuan proyeksi yang **belum** diposting.

        Bukan `cancel()`, dan sengaja tidak bisa dipanggil dari API mana
        pun: satu-satunya pemanggilnya
        `AccountingEventProcessor.supersede_unposted_projection()`, yang
        menagih seluruh syarat relasinya lebih dulu.

        Yang berubah **hanya** status, alasannya, dan satu kunci
        provenance. Tidak satu baris, akun, jumlah, dimensi, kolom
        sumber, atau kunci provenance lama yang disentuh — FIN-AJ1 tetap
        utuh, dan `verify_projection()` tetap mengenali jurnal ini
        sebagai proyeksi kejadian aslinya sesudahnya.

        `CANCELLED` dipilih dari status yang sudah ada: ia di luar
        `EDITABLE_JOURNAL_STATUSES` (tidak bisa disunting, tidak bisa
        diajukan) dan di luar `POSTABLE_STATUSES` (tidak bisa diposting),
        jadi draf yang sudah usang tidak bisa menyelinap ke buku besar.
        """
        locked = Journal.objects.select_for_update().get(pk=journal.pk)

        if locked.status in IMMUTABLE_JOURNAL_STATUSES:
            raise ValidationError({
                "status": (
                    f"Jurnal {locked.journal_number} sudah masuk buku "
                    "besar — yang sudah diposting dikoreksi lewat "
                    "pembalikan, bukan dicabut."
                ),
            })

        metadata = dict(locked.metadata or {})

        superseded_by = metadata.get("superseded_by_event")

        if superseded_by == superseding_event.pk:
            # Idempoten: pasangan yang sama, tidak ada yang ditulis lagi.
            return locked

        if superseded_by is not None:
            raise ValidationError({
                "automatic_journal": (
                    f"Jurnal {locked.journal_number} sudah digantikan "
                    f"kejadian #{superseded_by}."
                ),
            })

        metadata["superseded_by_event"] = superseding_event.pk

        locked.status = JournalStatus.CANCELLED
        locked.metadata = metadata
        locked.status_reason = (
            reason
            or f"Digantikan kejadian akuntansi #{superseding_event.pk}."
        )

        locked.save(update_fields=[
            "status", "metadata", "status_reason", "updated_at",
        ])

        return locked

    @classmethod
    def _write_lines(cls, *, journal: Journal, lines: list[dict]) -> Journal:
        journal.lines.all().delete()

        for number, payload in enumerate(lines, start=1):
            cls._create_line(journal=journal, number=number, payload=payload)

        cls.sync_totals(journal)

        return journal

    @classmethod
    def _create_line(cls, *, journal: Journal, number: int, payload: dict):
        dimensions = payload.pop("dimensions", None) or {}

        data = {
            "journal": journal,
            "line_number": number,
            "company": journal.company,
            "transaction_currency": payload.get("transaction_currency")
            or journal.currency,
            "exchange_rate": payload.get("exchange_rate")
            or journal.exchange_rate,
            **payload,
        }

        debit = data.get("debit") or ZERO
        credit = data.get("credit") or ZERO

        rate = data["exchange_rate"]

        # Nilai mata uang buku dihitung di sini, **tidak** diterima dari
        # klien. Membiarkannya dikirim berarti debit dan kredit bisa
        # seimbang dalam mata uang transaksi dan tidak seimbang di buku
        # besar — dan yang dibaca laporan justru yang kedua.
        data["base_debit"] = cls._to_base(debit, rate)
        data["base_credit"] = cls._to_base(credit, rate)

        line = JournalLine(**data)
        line.full_clean()
        line.save()

        cls._write_dimensions(line=line, values=dimensions)

        return line

    @staticmethod
    def _to_base(amount: Decimal, rate: Decimal) -> Decimal:
        if not amount:
            return ZERO

        return (Decimal(amount) * Decimal(rate)).quantize(Decimal("0.01"))

    @classmethod
    def _write_dimensions(cls, *, line: JournalLine, values: dict) -> None:
        """
        Menulis nilai dimensi tambahan sebuah baris.

        Dimensi inti tidak lewat sini — keduanya kolom pada barisnya
        sendiri. Kunci yang **tidak terdaftar** sebagai dimensi ditolak,
        bukan diabaikan: dimensi yang salah ketik dan diam-diam dibuang
        menghasilkan laporan yang kehilangan baris tanpa satu pun pesan,
        dan yang kehilangan itu baru ketahuan saat angkanya tidak cocok.
        """
        if not values:
            return

        registry = {
            row.code: row
            for row in AccountingDimension.objects.filter(
                is_deleted=False,
                is_core=False,
            )
        }

        unknown = sorted(set(values) - set(registry))

        if unknown:
            raise ValidationError({
                "dimensions": (
                    f"Dimensi tidak dikenal: {', '.join(unknown)}. "
                    "Daftarkan dulu di Finance → Setup → Accounting "
                    "Dimensions."
                ),
            })

        rows = []

        for code, raw in values.items():
            if raw in (None, ""):
                continue

            dimension = registry[code]

            value_id = None
            value_text = ""
            label = ""

            if isinstance(raw, dict):
                value_id = raw.get("id") or raw.get("value")
                value_text = str(raw.get("text") or "")
                label = str(raw.get("label") or "")
            elif isinstance(raw, int):
                value_id = raw
            else:
                value_text = str(raw)
                label = value_text

            rows.append(
                JournalLineDimension(
                    journal_line=line,
                    dimension=dimension,
                    dimension_code=code,
                    value_id=value_id,
                    value_text=value_text,
                    value_label=label or value_text,
                )
            )

        if rows:
            JournalLineDimension.objects.bulk_create(rows)

    # ------------------------------------------------------------------
    # Total
    # ------------------------------------------------------------------

    @staticmethod
    def sync_totals(journal: Journal) -> Journal:
        totals = (
            JournalLine.objects
            .filter(journal=journal, is_deleted=False)
            .aggregate(
                debit=Sum("debit"),
                credit=Sum("credit"),
                base_debit=Sum("base_debit"),
                base_credit=Sum("base_credit"),
            )
        )

        journal.total_debit = totals["debit"] or ZERO
        journal.total_credit = totals["credit"] or ZERO
        journal.base_total_debit = totals["base_debit"] or ZERO
        journal.base_total_credit = totals["base_credit"] or ZERO

        Journal.objects.filter(pk=journal.pk).update(
            total_debit=journal.total_debit,
            total_credit=journal.total_credit,
            base_total_debit=journal.base_total_debit,
            base_total_credit=journal.base_total_credit,
        )

        return journal

    @classmethod
    def assert_balanced(cls, journal: Journal) -> None:
        """
        Debit = kredit, diperiksa pada **kedua** mata uang.

        Memeriksa mata uang transaksi saja tidak cukup: pembulatan kurs
        bisa membuat ayat yang seimbang dalam dolar menjadi selisih satu
        rupiah di buku besar, dan buku besar yang tidak seimbang adalah
        neraca yang tidak pernah bisa ditutup.
        """
        count = JournalLine.objects.filter(
            journal=journal, is_deleted=False,
        ).count()

        if not count:
            raise ValidationError({
                "lines": (
                    "Jurnal tanpa baris tidak membukukan apa pun. Isi "
                    "minimal dua baris — satu debit, satu kredit."
                ),
            })

        cls.sync_totals(journal)

        if journal.total_debit != journal.total_credit:
            difference = journal.total_debit - journal.total_credit

            raise ValidationError({
                "lines": (
                    f"Debit dan kredit tidak seimbang. Debit "
                    f"{journal.total_debit:,.2f}, kredit "
                    f"{journal.total_credit:,.2f} — selisih "
                    f"{difference:,.2f}."
                ),
            })

        if journal.base_total_debit != journal.base_total_credit:
            difference = journal.base_total_debit - journal.base_total_credit

            raise ValidationError({
                "lines": (
                    "Nilai dalam mata uang buku besar tidak seimbang "
                    f"(selisih {difference:,.2f}). Selisih sekecil ini "
                    "biasanya pembulatan kurs — tambahkan baris "
                    "selisih kurs, jangan mengubah kursnya."
                ),
            })

    # ------------------------------------------------------------------
    # Cakupan data pada jalur tulis
    # ------------------------------------------------------------------

    @classmethod
    def assert_within_scope(cls, *, journal: Journal, user=None) -> None:
        """
        Cakupan data pada jalur **tulis**.

        `filter_queryset()` menjaga baca, ubah, dan hapus — `create`
        tidak pernah melewatinya. Tanpa pemeriksaan ini, admin yang
        dicakup ke satu perusahaan tetap bisa menerbitkan jurnal untuk
        perusahaan lain lewat satu request yang diketik tangan, dan
        dokumennya kemudian hilang dari layarnya sendiri. Lubang yang
        sama sudah dua kali ditemukan di modul HR; bentuk penutupnya
        disalin dari sana.

        **Memakai mesin yang sama dengan penyaringan daftar**
        (`DataScopeService.filter` atas satu baris), bukan salinan
        semantik AND/OR-nya — dua salinan aturan cakupan cepat atau
        lambat berbeda, dan yang satu akan membuka apa yang ditutup
        satunya.
        """
        if user is None or not getattr(user, "is_authenticated", False):
            return

        if user.is_superuser:
            return

        visible = DataScopeService.filter(
            Journal.objects.filter(pk=journal.pk),
            JOURNAL_SCOPE,
            user,
        )

        if visible.exists():
            return

        raise ValidationError({
            "company": (
                "Dokumen ini berada di luar kewenangan data Anda — "
                "perusahaan, site, atau unit pada salah satu barisnya "
                "tidak termasuk yang boleh Anda akses."
            ),
        })

    @classmethod
    def assert_may(cls, *, journal: Journal, user, permission: str, action: str):
        """
        Wewenang tindakan dokumen — izin **dan** cakupan dari izin itu.

        Lihat `apps.finance.services.authority`. Cakupan union di
        `assert_within_scope` tetap dipakai jalur tulis draf; yang di
        sini lebih sempit karena dihitung hanya dari role yang memberi
        izin tindakannya.
        """
        assert_finance_action(
            user=user,
            permission=permission,
            queryset=Journal.objects.filter(pk=journal.pk),
            scope=JOURNAL_SCOPE,
            action=action,
        )

    # ------------------------------------------------------------------
    # Pengajuan
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def submit(cls, *, journal: Journal, user=None, notes: str = ""):
        """
        Mengajukan jurnal ke engine approval yang sudah ada.

        Kalau tidak ada alur yang cocok, dokumen **langsung APPROVED**
        dan tidak ada instance yang terbentuk. Itu perilaku yang benar
        untuk tenant yang memang tidak mewajibkan persetujuan jurnal —
        menolak dengan "belum ada alur" akan membuat Finance tidak bisa
        dipakai sama sekali sampai seseorang mengonfigurasi approval
        yang tidak ia inginkan.
        """
        from apps.finance.workflow_handlers import _final_actor
        from apps.workflow.models import InstanceStatus
        from apps.workflow.services.workflow_service import WorkflowService

        cls.assert_may(
            journal=journal,
            user=user,
            permission=CHANGE_JOURNAL_PERMISSION,
            action="mengajukan jurnal",
        )

        cls.assert_editable(journal)
        cls.assert_balanced(journal)
        cls.assert_within_scope(journal=journal, user=user)

        FiscalPeriodService.assert_year_open(fiscal_year=journal.fiscal_year)
        FiscalPeriodService.assert_postable(
            period=journal.accounting_period,
            user=user,
            action="diajukan",
        )

        definition = cls._find_definition(journal)

        if definition is None:
            cls._set_status(
                journal=journal,
                status=JournalStatus.APPROVED,
                user=user,
                stamp="approved",
            )

            return None

        instance = WorkflowService.submit(
            document=journal,
            module=WORKFLOW_MODULE,
            document_type=WORKFLOW_DOCUMENT_TYPE,
            user=user,
            context=cls.workflow_context(journal),
            document_number=journal.journal_number,
            document_label=cls.workflow_label(journal),
            notes=notes,
            # **Instance, bukan id.** `WorkflowService.submit()`
            # meneruskan isi `scope` apa adanya ke
            # `WorkflowInstance.company` — mengirim id membuatnya gagal
            # dengan `ValueError: Cannot assign "1"` tepat di jalur
            # pengajuan, sesudah dokumennya lolos seluruh validasi.
            scope={"company": journal.company},
            # Pelaku akhir dibaca dari baris keputusannya, bukan
            # pengajunya — aturan yang sama dengan handler kotak masuk.
            on_complete=lambda wf, status: cls.apply_workflow_status(
                journal=journal,
                status=status,
                user=_final_actor(wf),
            ),
        )

        if instance.status == InstanceStatus.PENDING:
            cls._set_status(
                journal=journal,
                status=JournalStatus.SUBMITTED,
                user=user,
                stamp="submitted",
            )

        return instance

    @staticmethod
    def _find_definition(journal: Journal):
        """
        Alur yang berlaku untuk jurnal ini, atau `None`.

        Lewat resolver milik engine, **bukan** query yang disusun di
        sini. Dua alasan, dan yang kedua menentukan: `specificity`
        adalah `@property`, bukan kolom — `order_by("-specificity")`
        gagal di database, dan versi yang lolos pemeriksaan tipe
        sekalipun akan mengurutkan lewat sesuatu yang lain. Dan aturan
        cakupan berjenjang ("kolom kosong = berlaku untuk semua") sudah
        punya satu rumah; salinannya di modul akan menyimpang begitu
        engine menambah satu dimensi cakupan.

        Cakupannya cuma `company`. Jurnal tidak punya pegawai subjek,
        jadi branch/location/employee_group tidak bisa disimpulkan dari
        dokumennya — barisnya boleh menyebut beberapa site sekaligus.
        Alur yang menyebut lokasi karena itu tidak akan pernah cocok
        untuk jurnal, dan itu memang jawaban yang benar: meja
        persetujuan jurnal ditentukan perusahaan dan besarnya angka,
        bukan site salah satu barisnya.
        """
        from apps.workflow.services.definition_service import (
            WorkflowDefinitionResolver,
        )

        return WorkflowDefinitionResolver.match(
            module=WORKFLOW_MODULE,
            document_type=WORKFLOW_DOCUMENT_TYPE,
            company=journal.company_id,
        )

    @staticmethod
    def workflow_context(journal: Journal) -> dict:
        """
        Cuplikan nilai yang dibekukan saat pengajuan.

        Dibaca syarat step (`WorkflowStep.condition`), jadi isinya
        adalah hal-hal yang wajar jadi dasar aturan approval: besarnya
        jurnal, jenisnya, dan modul sumbernya. Angkanya dikirim sebagai
        float karena konteks disimpan sebagai JSON — `Decimal` tidak
        bisa diserialisasi, dan yang dilakukan syarat terhadapnya cuma
        perbandingan besar-kecil terhadap ambang yang diketik orang.
        """
        return {
            "journal_number": journal.journal_number,
            "journal_type": journal.journal_type,
            "company": journal.company_id,
            "company_name": journal.company.name,
            "posting_date": str(journal.posting_date),
            "period": journal.accounting_period.code,
            "currency": journal.currency.code,
            "amount": float(journal.base_total_debit),
            "total_debit": float(journal.total_debit),
            "total_credit": float(journal.total_credit),
            "source_module": journal.source_module,
            "source_type": journal.source_type,
            "line_count": journal.lines.filter(is_deleted=False).count(),
        }

    @staticmethod
    def workflow_label(journal: Journal) -> str:
        return (
            f"{journal.journal_number} · {journal.company.name} · "
            f"{journal.base_total_debit:,.2f} {journal.base_currency.code}"
        )

    # ------------------------------------------------------------------
    # Hasil alur
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def apply_workflow_status(cls, *, journal: Journal, status, user=None):
        """
        Dipanggil engine saat alurnya berhenti.

        **Tidak memposting sendiri.** Persetujuan dan pembukuan adalah
        dua tindakan yang berbeda, dan menyatukannya menghilangkan satu
        kesempatan terakhir memeriksa — approver menyatakan jurnalnya
        benar, akuntan yang membukukannya. Tenant yang menginginkan
        posting otomatis menyalakannya lewat
        `FinancePostingService.post_on_approval`.
        """
        from apps.workflow.models import InstanceStatus

        mapping = {
            InstanceStatus.APPROVED: JournalStatus.APPROVED,
            InstanceStatus.REJECTED: JournalStatus.REJECTED,
            InstanceStatus.CANCELLED: JournalStatus.DRAFT,
            InstanceStatus.RETURNED: JournalStatus.DRAFT,
        }

        target = mapping.get(status)

        if target is None:
            return journal

        stamp = "approved" if target == JournalStatus.APPROVED else None

        return cls._set_status(
            journal=journal,
            status=target,
            user=user,
            stamp=stamp,
        )

    @classmethod
    def _set_status(cls, *, journal, status, user=None, stamp=None, reason=""):
        data: dict = {"status": status}

        now = timezone.now()

        if stamp == "submitted":
            data["submitted_at"] = now
            data["submitted_by"] = user
        elif stamp == "approved":
            data["approved_at"] = now
            data["approved_by"] = user
        elif stamp == "cancelled":
            data["cancelled_at"] = now
            data["cancelled_by"] = user

        if reason:
            data["status_reason"] = reason

        for field, value in data.items():
            setattr(journal, field, value)

        Journal.objects.filter(pk=journal.pk).update(**data)

        return journal

    @classmethod
    @transaction.atomic
    def withdraw(cls, *, journal: Journal, user=None):
        """Menarik pengajuan yang masih menunggu, kembali ke Draft."""
        from apps.workflow.services.workflow_service import WorkflowService

        cls.assert_may(
            journal=journal,
            user=user,
            permission=CHANGE_JOURNAL_PERMISSION,
            action="menarik pengajuan jurnal",
        )

        journal.refresh_from_db(fields=["status"])

        if journal.status != JournalStatus.SUBMITTED:
            raise ValidationError({
                "status": (
                    "Hanya jurnal yang sedang menunggu persetujuan yang "
                    "bisa ditarik kembali."
                ),
            })

        instance = WorkflowService.instance_for(
            document=journal,
            module=WORKFLOW_MODULE,
            document_type=WORKFLOW_DOCUMENT_TYPE,
        )

        if instance is not None:
            # `comment=`, bukan `notes=` — argumen `WorkflowService.
            # cancel()` memang bernama begitu, dan kata kunci yang
            # salah di sini gagal sebagai TypeError tepat pada jalur
            # yang dipakai orang menarik pengajuannya sendiri.
            WorkflowService.cancel(
                instance=instance,
                user=user,
                comment="Ditarik kembali oleh pengaju.",
            )

        return cls._set_status(
            journal=journal,
            status=JournalStatus.DRAFT,
            user=user,
        )

    @classmethod
    @transaction.atomic
    def cancel(cls, *, journal: Journal, user=None, reason: str = ""):
        """
        Membatalkan jurnal yang belum diposting.

        Yang sudah diposting **tidak** dibatalkan — ia dibalik. Fakta
        akuntansi tidak pernah dicabut, ia dilawan dengan fakta yang
        berlawanan.
        """
        cls.assert_may(
            journal=journal,
            user=user,
            permission=CHANGE_JOURNAL_PERMISSION,
            action="membatalkan jurnal",
        )

        journal.refresh_from_db(fields=["status"])

        # FIN-AJ1. Membatalkan proyeksi meninggalkan kejadiannya PROCESSED
        # dan menunjuk hasil akuntansi yang sudah batal — dan `retry()`
        # menolak kejadian PROCESSED, jadi tidak ada jalan pulangnya.
        # Koreksi berangkat dari sumbernya.
        if cls.is_source_controlled(journal):
            journal.refresh_from_db(fields=["metadata"])

            raise AutomaticJournalLocked(journal, action="dibatalkan")

        if journal.status in IMMUTABLE_JOURNAL_STATUSES:
            raise ValidationError({
                "status": (
                    f"Jurnal {journal.journal_number} sudah diposting. "
                    "Yang sudah masuk buku besar dibalik lewat Reverse, "
                    "bukan dibatalkan."
                ),
            })

        # FIN-B1/B2. Yang sedang menunggu persetujuan ditarik dulu.
        # Membatalkannya langsung meninggalkan instance alur yang masih
        # PENDING — dan persetujuan yang datang sesudahnya memindahkan
        # jurnal yang sudah batal kembali ke APPROVED.
        if journal.status == JournalStatus.SUBMITTED:
            raise ValidationError({
                "status": (
                    f"Jurnal {journal.journal_number} sedang menunggu "
                    "persetujuan. Tarik kembali pengajuannya (Withdraw) "
                    "sebelum membatalkannya."
                ),
            })

        if journal.status == JournalStatus.CANCELLED:
            raise ValidationError({
                "status": f"Jurnal {journal.journal_number} sudah dibatalkan.",
            })

        return cls._set_status(
            journal=journal,
            status=JournalStatus.CANCELLED,
            user=user,
            stamp="cancelled",
            reason=reason,
        )


class JournalLineService(BaseMasterService):
    """
    Baris jurnal sebagai resource tersendiri.

    Ada **di samping** `JournalService.replace_lines`, bukan
    menggantikannya, dan keduanya memang dipakai jalur yang berbeda:

    * Yang di sini melayani grid di layar — akuntan menambah baris satu
      per satu, dan dokumennya memang melewati keadaan tidak seimbang
      selama diketik. Itu wajar; keseimbangan ditagih saat Submit dan
      saat Post, bukan di antara dua baris.
    * `replace_lines` melayani jalur mesin — penerbitan dari kejadian
      akuntansi dan penyalinan jurnal pembalik, yang menyusun seluruh
      ayatnya sekaligus.

    Yang **tidak** boleh berbeda di antara keduanya: pengisian nilai
    mata uang buku, penomoran baris, dan penjagaan editability. Ketiganya
    karena itu dipanggil dari sini lewat helper yang sama.
    """

    model = JournalLine

    @staticmethod
    def list():
        return (
            JournalLine.objects
            .filter(is_deleted=False)
            .select_related(
                "journal",
                "account",
                "cost_center",
                "location",
                "department",
                "transaction_currency",
            )
            .prefetch_related("dimension_values")
            .order_by("journal_id", "line_number")
        )

    @classmethod
    def prepare_create_data(cls, *, data, user=None, **kwargs):
        journal = data.get("journal")

        if journal is None:
            raise ValidationError({
                "journal": "Baris jurnal harus menyebut jurnalnya.",
            })

        JournalService.assert_content_mutable(journal, action="ditambah barisnya")

        data.setdefault("company", journal.company)
        data.setdefault("transaction_currency", journal.currency)
        data.setdefault("exchange_rate", journal.exchange_rate)

        if not data.get("line_number"):
            # Nomor berikutnya, dihitung dari yang ada — termasuk baris
            # yang sudah dihapus, supaya nomor tidak dipakai ulang di
            # satu dokumen. Nomor yang berulang di dokumen yang sama
            # membuat rujukan "baris 3" jadi ambigu.
            last = (
                JournalLine.objects
                .filter(journal=journal)
                .order_by("-line_number")
                .values_list("line_number", flat=True)
                .first()
            )

            data["line_number"] = (last or 0) + 1

        return cls._apply_base_amounts(data)

    @classmethod
    def prepare_update_data(cls, *, instance, data, user=None, **kwargs):
        JournalService.assert_content_mutable(
            instance.journal, action="disunting barisnya",
        )

        merged = {
            "debit": data.get("debit", instance.debit),
            "credit": data.get("credit", instance.credit),
            "exchange_rate": data.get(
                "exchange_rate", instance.exchange_rate,
            ),
        }

        data.update(cls._apply_base_amounts(merged))

        # Pindah ke jurnal lain lewat PATCH adalah penerbitan yang
        # menyamar jadi penyuntingan — dan jurnal tujuannya mungkin
        # sudah diposting.
        data.pop("journal", None)

        return data

    @staticmethod
    def _apply_base_amounts(data: dict) -> dict:
        rate = data.get("exchange_rate") or Decimal("1.000000")

        data["base_debit"] = JournalService._to_base(
            data.get("debit") or ZERO, rate,
        )
        data["base_credit"] = JournalService._to_base(
            data.get("credit") or ZERO, rate,
        )

        return data

    @classmethod
    def after_create(cls, *, instance, user=None, **kwargs):
        cls._sync(instance)

        return instance

    @classmethod
    def after_update(cls, *, instance, user=None, **kwargs):
        cls._sync(instance)

        return instance

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        JournalService.assert_content_mutable(
            instance.journal, action="dihapus barisnya",
        )

    @classmethod
    def after_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        cls._sync(instance)

    @staticmethod
    def _sync(line: JournalLine) -> None:
        """
        Total kepala dokumen ditulis ulang setiap kali barisnya berubah.

        Kaki tabel di layar membaca total ini, bukan menjumlahkan baris
        yang sedang tampil — dan grid yang berhalaman cuma tahu halaman
        yang sedang dibuka.
        """
        JournalService.sync_totals(line.journal)
