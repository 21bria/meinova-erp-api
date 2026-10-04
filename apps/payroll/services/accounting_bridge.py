"""
Jembatan akuntansi Finalize — payload PF-0C → kejadian `PAYROLL_POSTED`.

Satu tempat, satu pemanggil. `PayrollRunService.finalize()` memanggilnya
**sekali**, sesudah gerbang PF-0D menyetujui payload dan sesudah run
dikunci — di dalam transaksi Finalize yang sama. Tidak ada signal, tidak
ada hook model, tidak ada pemanggilan dari view atau serializer: jalur
yang menerbitkan jurnal harus terbaca dari satu berkas.

Yang dilakukannya persis satu hal: menyerahkan payload yang **sudah**
disahkan gerbang ke `AccountingEventProcessor.record_required()`, lalu
menerjemahkan kegagalannya jadi `PayrollAccountingError` ber-kode.

Yang **tidak** dilakukannya:

* menyusun ulang payload — yang dikirim persis milik gerbang;
* menghitung ulang payroll;
* menentukan akun, sisi, atau apakah jurnalnya diposting — itu kebijakan
  Finance (`auto_post`), dan kebijakan gaji bawaannya menerbitkan DRAFT;
* memberi siapa pun wewenang Finance. Yang memfinalisasi payroll adalah
  **aktor sumber** kejadian: namanya tercatat sebagai pembuat kejadian
  dan jurnal draf, tapi ia tidak menyetujui dan tidak memposting apa pun.

**Gagal = Finalize batal seluruhnya.** Pemetaan yang hilang atau ambigu,
kebijakan yang tidak ada, periode Finance yang tidak menerima dokumen,
akun yang tidak aktif — semuanya melempar, dan transaksi Finalize
membatalkan slip, status run, kejadian, maupun jurnal drafnya bersama.
Tidak ada akun penampung, tidak ada baris penyeimbang, tidak ada akun
bawaan.

Ini **membalik** satu keputusan PF-0D dengan sengaja: dulu kalender
Finance yang belum dibuka tidak menghalangi Finalize, karena belum ada
jurnal yang diterbitkan. Sekarang jurnal draf adalah bagian dari
Finalize, dan jurnal tanpa periode tidak bisa ada. Gerbangnya sendiri
tidak berubah — ia tetap cuma melaporkan `period_problem`.
"""

from __future__ import annotations

from apps.payroll.services.accounting import PayrollAccountingError


EVENT_TYPE = "PAYROLL_POSTED"
SOURCE_MODULE = "payroll"
SOURCE_TYPE = "payroll_run"


def idempotency_key(run_id: int) -> str:
    """
    Identitas kejadian akuntansi sebuah run. **Dibekukan PF-0F.**

    `payroll:payroll_run:<pk>:posted` — struktural, bukan isi:

    * `pk` run tidak pernah berubah, dan run koreksi adalah run lain
      dengan pk lain, jadi kejadiannya juga lain;
    * schema tenant memisahkan tabel kejadiannya, jadi pk yang sama di
      tenant lain tidak pernah bertemu penanda ini;
    * awalan `payroll:payroll_run:` menutup kemungkinan bertabrakan
      dengan modul lain.

    Digest PF-0C **sengaja bukan** bagian penanda. Kalau iya, run yang
    sama dengan isi berbeda akan lahir sebagai kejadian kedua — padahal
    yang benar menolaknya. Digest tetap sidik jari isinya, dan
    `record_required()` menolak penanda yang sama dengan isi berbeda.
    """
    return f"payroll:payroll_run:{run_id}:posted"


class PayrollAccountingBridge:
    """Payload yang sudah disahkan → kejadian + jurnal draf Finance."""

    # ------------------------------------------------------------------
    # PF-0G — keadaan proyeksi sebuah run, dibaca payroll tanpa mengenal
    # model Finance
    # ------------------------------------------------------------------

    @classmethod
    def projection_state(cls, *, run) -> dict:
        """
        Keadaan akuntansi sebuah run: ada kejadiannya, sudah diproses,
        sudah digantikan, jurnalnya sudah masuk buku besar, dan id-nya.

        Payroll bertanya dengan **penandanya sendiri** dan menerima data
        biasa. Nama status, kelas jurnal, dan definisi "sudah masuk buku
        besar" tetap milik Finance — tidak ada satu pun model Finance
        yang disebut di modul ini (dijaga test regresi Finance).
        """
        from apps.finance.services.event import AccountingEventProcessor

        return AccountingEventProcessor.projection_state(
            idempotency_key=idempotency_key(run.pk),
        )

    @classmethod
    def supersede(cls, *, old_run, new_run, new_event_id, user=None) -> dict:
        """
        Mencabut keberlakuan proyeksi run lama yang **belum** diposting.

        Satu-satunya pemanggil `PayrollRunService.finalize()` untuk run
        koreksi, sesudah proyeksi penggantinya benar-benar terbit. Yang
        sudah diposting tidak pernah sampai ke sini: pemanggilnya
        memeriksa `projection_state()["posted"]` lebih dulu, dan Finance
        menolaknya sekali lagi sendiri (`supersede_posted_journal`) —
        sejarah buku besar dikoreksi lewat pembalikan Finance oleh aktor
        Finance, bukan dari modul payroll.
        """
        from apps.finance.services.event import (
            AccountingEventError,
            AccountingEventProcessor,
        )

        try:
            return AccountingEventProcessor.supersede_projection_for(
                old_key=idempotency_key(old_run.pk),
                new_event_id=new_event_id,
                user=user,
                reason=(
                    "Digantikan run koreksi "
                    f"{cls._label(new_run)}."
                ),
            )
        except AccountingEventError as error:
            raise PayrollAccountingError(
                _message(error), code=error.error_code,
            ) from error

    @staticmethod
    def _label(run) -> str:
        return str(run.document_number or run.pk)

    @classmethod
    def record(cls, *, run, gate, user=None, replaces_run=None) -> dict:
        """
        Mencatat `PAYROLL_POSTED` untuk run ini dan memastikan jurnalnya
        terbit.

        `gate` adalah `AccountingGateResult` yang baru saja dikembalikan
        `PayrollAccountingGate.evaluate()` di Finalize yang sama.
        `event_date` adalah akhir periode payroll — tanggal yang sama yang
        dipakai gerbang membaca konfigurasi Finance (PF-0B §7).

        Impor di dalam fungsi, bukan di kepala berkas, dengan alasan yang
        sama dengan gerbangnya: Payroll menyentuh Finance hanya lewat pintu
        yang disebut di sini, dan pintunya terbaca di tempat ia dipakai.
        """
        from apps.finance.services.event import (
            AccountingEventError,
            AccountingEventProcessor,
        )

        key = idempotency_key(run.pk)

        # PF-0G. Untuk run koreksi: **penanda** kejadian yang digantikan
        # proyeksi ini. Finance yang meresolusinya jadi kejadian,
        # menyimpan penunjuknya di metadata jurnal, dan memakainya
        # menolak pembukuan pengganti selama ayat lamanya masih hidup.
        replaces_key = (
            idempotency_key(replaces_run.pk) if replaces_run is not None else ""
        )

        try:
            event = AccountingEventProcessor.record_required(
                event_type=EVENT_TYPE,
                source_module=SOURCE_MODULE,
                source_type=SOURCE_TYPE,
                source_id=str(run.pk),
                source_reference=run.document_number or "",
                company=run.company,
                event_date=run.period.end_date,
                payload=gate.payload,
                idempotency_key=key,
                user=user,
                replaces_key=replaces_key,
            )
        except AccountingEventError as error:
            raise PayrollAccountingError(
                _message(error),
                code=error.error_code,
            ) from error

        journal = event.generated_journal

        return {
            "event_id": event.pk,
            "replaces_event_id": (
                (journal.metadata or {}).get("replaces_event")
            ),
            "event_status": event.status,
            "idempotency_key": key,
            "digest": gate.digest,
            "journal_id": journal.pk,
            "journal_number": journal.journal_number or "",
            "journal_status": journal.status,
        }


def _message(error) -> str:
    messages = getattr(error, "message_dict", None) or {}

    for values in messages.values():
        if values:
            return str(values[0])

    return "; ".join(error.messages)
