"""
Menilai satu pengajuan cuti terhadap `LeavePolicy` yang berlaku.

Arahnya berlawanan dengan `LeaveEntitlementCalculator`: yang itu
menerjemahkan aturan jadi **angka di kartu**, yang ini menilai **satu
dokumen** terhadap aturan yang sama. Keduanya berangkat dari resolver
yang sama (`LeavePolicyResolver`), jadi aturan yang menang untuk kartu
seseorang adalah aturan yang menang untuk pengajuannya — dua pencari
aturan yang harus tetap sama adalah persis cara keduanya diam-diam
berbeda.

Kenapa ini perlu ada
--------------------
Cuti menikah, melahirkan, dan duka tidak punya saldo: tidak ada angka
yang berkurang, jadi tidak ada apa pun yang menahan seseorang
mengajukannya tiga kali setahun. Sampai sekarang batasnya memang tidak
ada di mana pun — `LeaveType` cuma kode dan nama, dan satu-satunya
penjagaan di modul Cuti adalah tumpang tindih tanggal. Yang menutupnya
kolom-kolom baru di `LeavePolicy` (`max_days`, `per_event`,
`document_required`, `history_check`), dan modul inilah yang membacanya.

Tiga tingkat temuan, dan hanya satu yang menolak
------------------------------------------------
`BLOCK` menolak; `REVIEW` dan `WARN` hanya menandai. Itu bukan
kelonggaran — cuti per kejadian memang **boleh** berulang: orang bisa
menikahkan anak keduanya, dan bisa berduka dua kali dalam setahun. Yang
tidak bisa diputuskan kode adalah apakah kejadiannya kejadian yang
berbeda, dan satu-satunya yang bisa menjawabnya adalah orang yang
memegang surat keterangannya. Menolak otomatis berarti hak yang sah
hilang tanpa ada tempat membantahnya; menerima diam-diam berarti tidak
ada yang pernah memeriksanya.

Kapan yang BLOCK benar-benar menahan
------------------------------------
Enforcement-nya **tidak seragam**, dan itu disengaja:

- **Jalur pengajuan** (DRAFT/SUBMITTED) — `max_days` dan riwayat
  ber-`block` menolak sejak dokumennya dibuat.
- **Saat Submit** — ketiganya menolak, termasuk `document_required`.
  Dokumennya sengaja tidak diwajibkan lebih awal: surat dokter lazim
  baru ada sesudah orangnya pulang berobat, dan draft yang tidak bisa
  disimpan sampai suratnya lengkap membuat orang mengetik ulang
  seluruh isian.
- **Jalur pencatatan** (RECORDED) — tidak ada yang menahan. HR mencatat
  cuti yang **sudah terjadi**, dan menolaknya berarti fakta itu tidak
  punya tempat tersimpan di mana pun. Temuannya tetap dihitung dan
  tetap tampil sebagai peringatan. Alasan yang sama dengan
  `TravelRequestService.issue_leave_records` yang tidak pernah melempar.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from datetime import date
from decimal import Decimal

from apps.administration.models import LeavePolicy
from apps.administration.models.references.leave_policy import (
    LeaveHistoryAction,
)

from .eligibility import LeaveEligibilityResolver
from .entitlement import LeavePolicyResolver


# Berapa baris riwayat yang ikut di payload. Yang membaca peringatan
# butuh melihat kejadian sebelumnya, bukan seluruh karier orangnya —
# dan daftar yang panjang di dalam sebuah peringatan justru berhenti
# dibaca. Jumlah seluruhnya tetap dilaporkan lewat `history_total`.
HISTORY_LIMIT = 5

ZERO = Decimal("0.0")

# Kartu saldo menyimpan satu angka di belakang koma
# (`LeaveBalance.entitlement` dkk.), sementara `total_days` bisa datang
# sebagai `Decimal("3")` dari `LeaveDayCalculator`. Tanpa diseragamkan,
# satu kalimat penolakan memuat dua bentuk angka yang sama —
# "tinggal 2.0 hari, meminta 3 hari" — dan yang membacanya menyangka
# keduanya diukur dengan satuan berbeda.
DAYS_PRECISION = Decimal("0.1")


def as_days(value) -> Decimal:
    """Menyeragamkan bentuk angka hari ke satu desimal."""
    if value is None:
        return ZERO

    return Decimal(value).quantize(DAYS_PRECISION)


class RuleLevel:
    """
    Tiga tingkat, dan pembedanya **apa yang terjadi**, bukan seberapa
    penting temuannya.

    `BLOCK` menahan penyimpanan. `REVIEW` menandai dokumen sebagai butuh
    diperiksa orang dan ikut terbawa sampai meja terakhir. `WARNING`
    ditampilkan lalu selesai.
    """

    BLOCK = "block"
    REVIEW = "review"
    WARNING = "warning"


@dataclass(frozen=True)
class LeaveRuleFinding:
    """Satu temuan, sudah berbentuk kalimat yang bisa dibaca orang."""

    # Nama aturannya (`max_days`, `document_required`, `history`) —
    # dipakai frontend memilih ikon dan dipakai test menunjuk temuan
    # tanpa mencocokkan kalimatnya. Pesan ditulis untuk dibaca orang
    # dan akan diubah redaksinya cepat atau lambat.
    code: str

    level: str
    message: str

    # Kolom yang ditempeli kalau temuan ini menolak. Error tanpa nama
    # field tidak menempel di kolom mana pun dan gagal tanpa suara di
    # sebagian layar — pelajaran dari `normalizeApiErrors`.
    field: str = "non_field_errors"

    @property
    def is_blocking(self) -> bool:
        return self.level == RuleLevel.BLOCK


@dataclass(frozen=True)
class LeaveRuleReport:
    """Hasil penilaian satu pengajuan."""

    policy: LeavePolicy | None
    findings: list[LeaveRuleFinding] = dataclass_field(default_factory=list)

    # Cuti sejenis yang pernah dipakai pegawai ini, sudah berbentuk
    # dict siap kirim. Kosong kalau `history_check` mati.
    history: list[dict] = dataclass_field(default_factory=list)
    history_total: int = 0

    # Apakah riwayatnya benar-benar dicari. Dibawa sebagai penanda,
    # **bukan** disimpulkan dari `history` yang kosong: "sudah dicari,
    # tidak ada" dan "belum dicari" adalah dua keadaan yang berbeda,
    # dan yang membacanya tidak punya cara membedakannya kalau
    # keduanya berbentuk daftar kosong. Layar daftar sengaja tidak
    # mencarinya (lihat `evaluate`), jadi tanpa penanda ini sebuah
    # baris akan terbaca "bersih" di tabel dan "perlu diperiksa" di
    # dialognya sendiri.
    history_evaluated: bool = True

    # Keadaan kartu saldo pegawai untuk jenis cuti dan tahun dokumen
    # ini, sudah berbentuk dict siap kirim. `None` = tidak dinilai
    # (aturannya bukan aturan bersaldo, atau layar daftar yang sengaja
    # melewatinya).
    balance: dict | None = None

    # Apakah saldonya benar-benar diperiksa. Dibawa sebagai penanda,
    # sebentuk dengan `history_evaluated` dan karena alasan yang sama:
    # "sudah diperiksa, cukup" dan "belum diperiksa" adalah dua keadaan
    # berbeda, dan keduanya sama-sama berbentuk temuan kosong. Tanpa
    # penanda ini sebuah baris terbaca aman di tabel lalu ditolak saat
    # dibuka.
    balance_evaluated: bool = False

    @property
    def uses_balance(self) -> bool:
        """
        Bawaannya **True** saat aturannya belum ada.

        Jenis cuti tanpa policy tetap diperlakukan seperti sebelumnya:
        saldonya tidak terbit (generator melewatinya) tapi tidak ada
        pula aturan baru yang tiba-tiba berlaku untuknya. Mengembalikan
        False di sini akan membuat seluruh jenis cuti yang masternya
        belum diisi berpindah perilaku tanpa ada yang mengubah apa pun.
        """
        if self.policy is None:
            return True

        return bool(self.policy.uses_balance)

    @property
    def blocking(self) -> list[LeaveRuleFinding]:
        return [row for row in self.findings if row.is_blocking]

    @property
    def warnings(self) -> list[LeaveRuleFinding]:
        return [row for row in self.findings if not row.is_blocking]

    @property
    def needs_review(self) -> bool:
        """
        Ada temuan yang harus dilihat orang sebelum dokumen ini lewat.

        Dibaca alur persetujuan lewat `workflow_context`, jadi sebuah
        step boleh dibuat bersyarat "hanya kalau butuh diperiksa" tanpa
        menebak dari jenis cutinya.
        """
        return any(
            row.level in (RuleLevel.REVIEW, RuleLevel.BLOCK)
            for row in self.findings
        )

    def as_dict(self) -> dict:
        """Bentuk siap kirim ke frontend."""
        return {
            "policy_code": getattr(self.policy, "code", None),
            "policy_name": getattr(self.policy, "name", None),
            "uses_balance": self.uses_balance,
            "per_event": bool(getattr(self.policy, "per_event", False)),
            "max_days": (
                str(self.policy.max_days)
                if self.policy is not None
                and self.policy.max_days is not None
                else None
            ),
            "document_required": bool(
                getattr(self.policy, "document_required", False),
            ),
            "needs_review": self.needs_review,
            "findings": [
                {
                    "code": row.code,
                    "level": row.level,
                    "field": row.field,
                    "message": row.message,
                }
                for row in self.findings
            ],
            "history": list(self.history),
            "history_total": self.history_total,
            "history_evaluated": self.history_evaluated,
            "balance": self.balance,
            "balance_evaluated": self.balance_evaluated,
        }


class LeaveRuleEvaluator:
    """
    Instansiabel, dan itu yang membuatnya boleh dipakai per baris.

    Satu instance = satu halaman daftar, dengan memo aturan di dalamnya.
    `LeavePolicyResolver.resolve` menembak satu query tiap dipanggil;
    tanpa memo, daftar 20 baris berarti 20 query untuk aturan yang
    lazimnya cuma satu baris di seluruh tenant. Pola yang sama dengan
    `LeaveEligibilityResolver`.
    """

    def __init__(self) -> None:
        self._policies: dict[tuple, LeavePolicy | None] = {}

        # Kartu saldo per (pegawai, jenis cuti, tahun). Di-memo karena
        # satu halaman daftar milik satu pegawai — kasus "cuti saya" —
        # akan menembak query yang sama untuk tiap barisnya.
        self._balances: dict[tuple, object] = {}

        self._eligibility = LeaveEligibilityResolver()

    # ------------------------------------------------------------------
    # Aturan yang berlaku
    # ------------------------------------------------------------------

    def policy_for(self, employee, leave_type) -> LeavePolicy | None:
        if employee is None or leave_type is None:
            return None

        organization = getattr(employee, "organization", None)
        employment = getattr(employee, "employment", None)

        key = (
            getattr(organization, "company_id", None),
            getattr(employment, "employee_group_id", None),
            getattr(employment, "employment_type_id", None),
            getattr(leave_type, "pk", None),
        )

        if key not in self._policies:
            self._policies[key] = LeavePolicyResolver.resolve(
                employee=employee,
                leave_type=leave_type,
            )

        return self._policies[key]

    # ------------------------------------------------------------------
    # Penilaian
    # ------------------------------------------------------------------

    def evaluate(
        self,
        *,
        employee,
        leave_type,
        start_date: date | None = None,
        total_days: Decimal | None = None,
        has_document: bool = False,
        exclude_pk=None,
        with_history: bool = True,
        with_balance: bool = True,
        own_deduction: Decimal | None = None,
    ) -> LeaveRuleReport:
        """
        Menilai satu pengajuan. **Tidak pernah melempar** — yang
        memutuskan menahan atau tidak adalah pemanggilnya.

        Pemisahan itu disengaja: modul ini dipakai dua arah yang
        berlawanan. Service memakainya untuk **menolak**; serializer
        memakainya untuk **menampilkan** peringatan pada dokumen yang
        sudah tersimpan — termasuk dokumen yang aturannya berubah
        sesudah ia dibuat. Kalau penilaiannya melempar, layar daftar
        ikut mati gara-gara satu baris yang tidak lagi memenuhi aturan
        yang baru.

        `with_history=False` melewati pencarian riwayatnya. Dipakai
        layar **daftar**: pencarian itu dua query per baris, dan satu
        halaman berisi dua puluh cuti berarti empat puluh query untuk
        keterangan yang tidak muat di kolom tabel mana pun. Aturan
        selebihnya tetap dinilai — resolvernya memoized, jadi seluruh
        halaman cuma menambah satu query.

        `with_balance=False` melewati pemeriksaan saldo, dan dipakai
        layar daftar karena alasan yang sama. `own_deduction` adalah
        bagian saldo yang **sudah** dipotong dokumen ini sendiri —
        dokumen RECORDED/APPROVED yang sedang disunting sudah ikut
        terhitung di `used`, jadi tanpa dikembalikan lebih dulu ia akan
        diadu dengan sisa yang sudah dikurangi dirinya sendiri.
        """
        policy = self.policy_for(employee, leave_type)

        if policy is None:
            return LeaveRuleReport(policy=None)

        findings: list[LeaveRuleFinding] = []

        findings.extend(
            self._check_max_days(policy=policy, total_days=total_days),
        )

        balance, balance_findings = (
            self._check_balance(
                policy=policy,
                employee=employee,
                leave_type=leave_type,
                start_date=start_date,
                total_days=total_days,
                own_deduction=own_deduction or ZERO,
            )
            if with_balance
            else (None, [])
        )

        findings.extend(balance_findings)

        findings.extend(
            self._check_document(policy=policy, has_document=has_document),
        )

        history, history_total, history_findings = (
            self._check_history(
                policy=policy,
                employee=employee,
                leave_type=leave_type,
                start_date=start_date,
                exclude_pk=exclude_pk,
            )
            if with_history
            else ([], 0, [])
        )

        findings.extend(history_findings)

        return LeaveRuleReport(
            policy=policy,
            findings=findings,
            history=history,
            history_total=history_total,
            history_evaluated=with_history,
            balance=balance,
            balance_evaluated=with_balance and bool(policy.uses_balance),
        )

    # ------------------------------------------------------------------
    # Batas hari
    # ------------------------------------------------------------------

    @staticmethod
    def _check_max_days(*, policy, total_days) -> list[LeaveRuleFinding]:
        """
        Dinilai terhadap `total_days` — angka yang **tersimpan di
        dokumennya**, bukan terhadap selisih tanggal.

        Bedanya nyata dan sengaja: `LeaveDayCalculator` menghitung hari
        kerja yang hilang, jadi cuti menikah Jumat–Minggu bagi pegawai
        kantor berjumlah satu hari, bukan tiga. Membandingkan selisih
        tanggal akan menolak pengajuan yang di dokumennya sendiri
        tertulis satu hari — dan yang membaca penolakannya tidak punya
        cara mencocokkan angka yang disebut pesan itu dengan angka mana
        pun di layar.
        """
        if policy.max_days is None or total_days is None:
            return []

        if Decimal(total_days) <= Decimal(policy.max_days):
            return []

        return [
            LeaveRuleFinding(
                code="max_days",
                level=RuleLevel.BLOCK,
                field="total_days",
                message=(
                    f"{policy.code} membatasi {policy.max_days} hari "
                    f"untuk satu pengajuan, sedangkan dokumen ini "
                    f"{total_days} hari. Perpendek tanggalnya, atau "
                    f"ubah batasnya di Leave Policy."
                ),
            ),
        ]

    # ------------------------------------------------------------------
    # Dokumen pendukung
    # ------------------------------------------------------------------

    @staticmethod
    def _check_document(*, policy, has_document) -> list[LeaveRuleFinding]:
        if not policy.document_required or has_document:
            return []

        return [
            LeaveRuleFinding(
                code="document_required",
                level=RuleLevel.BLOCK,
                field="uploaded_file",
                message=(
                    f"{policy.code} mewajibkan dokumen pendukung — "
                    f"surat dokter, surat nikah, atau keterangan "
                    f"resmi lain. Lampirkan dulu sebelum mengajukan."
                ),
            ),
        ]

    # ------------------------------------------------------------------
    # Saldo
    # ------------------------------------------------------------------

    def balance_for(self, employee, leave_type, year: int):
        """Kartu saldo pegawai untuk satu jenis cuti, di-memo per tahun."""
        from apps.hr.models import LeaveBalance

        key = (
            getattr(employee, "pk", None),
            getattr(leave_type, "pk", None),
            year,
        )

        if key not in self._balances:
            self._balances[key] = (
                LeaveBalance.objects
                .filter(
                    employee=employee,
                    leave_type=leave_type,
                    year=year,
                    is_deleted=False,
                )
                .first()
            )

        return self._balances[key]

    def _check_balance(
        self,
        *,
        policy,
        employee,
        leave_type,
        start_date,
        total_days,
        own_deduction: Decimal,
    ):
        """
        Apakah saldonya cukup untuk pengajuan ini.

        **Hanya untuk aturan bersaldo.** Cuti menikah dan duka tidak
        punya kartu sama sekali; memeriksanya di sana berarti setiap
        pengajuan ditolak oleh angka yang memang tidak pernah ada.

        Tiga keadaan, dan hanya dua yang menahan:

        - **Kartunya ada dan kurang** → BLOCK. Ini permintaan aslinya:
          sisa 2, diminta 3, ditolak.
        - **Kartunya tidak ada dan pegawainya memang belum berhak** →
          BLOCK, dengan menyebut tanggal ia mulai berhak. Jatahnya nol
          bukan karena datanya belum lengkap, melainkan karena masa
          tunggunya belum lewat — dan itu bisa dijawab tanpa menebak.
        - **Kartunya tidak ada dan kelayakannya tidak menolak** →
          REVIEW. Ini kekurangan penyiapan data (`generate_leave_balances`
          belum dijalankan untuk tahun itu), bukan kesalahan pengajunya,
          dan menolak di sini mengunci orang pada hal yang tidak bisa ia
          perbaiki sendiri. Ditandai supaya tetap terlihat.

        Tahunnya diambil dari `start_date`, sama persis dengan
        `LeaveBalanceService.recalculate_used` — cuti yang melintasi
        pergantian tahun dihitung penuh di tahun mulainya, dan
        memeriksanya terhadap kartu tahun lain berarti menahan
        pengajuan dengan angka yang tidak akan pernah dipotong.
        """
        if not policy.uses_balance:
            return None, []

        if start_date is None:
            return None, []

        year = start_date.year

        balance = self.balance_for(employee, leave_type, year)

        requested = as_days(total_days)

        if balance is None:
            return self._missing_balance(
                employee=employee,
                leave_type=leave_type,
                start_date=start_date,
                year=year,
                requested=requested,
            )

        # Dokumen yang sudah memotong saldo dan sedang disunting harus
        # mengembalikan potongannya sendiri lebih dulu. Tanpa itu, cuti
        # RECORDED 3 hari yang diubah jadi 4 diadu dengan sisa yang
        # sudah dikurangi 3 — dan yang tampil di layar adalah penolakan
        # yang angkanya tidak cocok dengan angka mana pun di kartunya.
        available = as_days(balance.remaining + (own_deduction or ZERO))

        info = {
            "exists": True,
            "year": year,
            "entitlement": str(balance.entitlement),
            "carried_over": str(balance.carried_over),
            "opening_balance": str(balance.opening_balance),
            "adjustment": str(balance.adjustment),
            "used": str(balance.used),
            "remaining": str(balance.remaining),
            "available": str(available),
            "requested": str(requested),
            "sufficient": requested <= available,
        }

        if requested <= available:
            return info, []

        return info, [
            LeaveRuleFinding(
                code="insufficient_balance",
                level=RuleLevel.BLOCK,
                field="total_days",
                message=(
                    f"Sisa {getattr(leave_type, 'name', 'cuti')} "
                    f"tahun {year} tinggal {available} hari, sedangkan "
                    f"dokumen ini meminta {requested} hari. Perpendek "
                    f"tanggalnya, atau tambahkan saldonya lewat "
                    f"Leave Balance."
                ),
            ),
        ]

    def _missing_balance(
        self,
        *,
        employee,
        leave_type,
        start_date,
        year: int,
        requested: Decimal,
    ):
        """Kartunya belum ada — kelayakannya yang menentukan artinya."""
        eligibility = self._eligibility.for_employee(employee, leave_type)

        eligible = eligibility.is_eligible_on(start_date)

        info = {
            "exists": False,
            "year": year,
            "available": "0.0",
            "requested": str(requested),
            "sufficient": False,
            "eligible_date": (
                eligibility.eligible_date.isoformat()
                if eligibility.eligible_date
                else None
            ),
        }

        # `None` bukan sinonim False: ia berarti tidak bisa dinilai
        # (Join Date belum diisi). Menolak di keadaan itu menandai
        # pegawai yang sudah sepuluh tahun bekerja sebagai belum
        # berhak — pelajaran yang sama dengan `OpeningValidation`.
        if eligible is False:
            info["sufficient"] = requested <= ZERO

            if requested <= ZERO:
                return info, []

            return info, [
                LeaveRuleFinding(
                    code="not_yet_eligible",
                    level=RuleLevel.BLOCK,
                    field="leave_type",
                    message=(
                        f"Pegawai baru berhak atas "
                        f"{getattr(leave_type, 'name', 'cuti ini')} "
                        f"mulai {eligibility.eligible_date:%d/%m/%Y} — "
                        f"{eligibility.reason or 'sesuai masa tunggu di Leave Policy'}."
                    ),
                ),
            ]

        if requested <= ZERO:
            return info, []

        return info, [
            LeaveRuleFinding(
                code="balance_missing",
                level=RuleLevel.REVIEW,
                field="leave_type",
                message=(
                    f"Kartu saldo {getattr(leave_type, 'name', 'cuti')} "
                    f"tahun {year} belum terbit untuk pegawai ini, jadi "
                    f"sisanya tidak bisa diperiksa. Jalankan "
                    f"generate_leave_balances untuk tahun {year}, atau "
                    f"periksa Join Date-nya."
                ),
            ),
        ]

    # ------------------------------------------------------------------
    # Riwayat
    # ------------------------------------------------------------------

    def _check_history(
        self,
        *,
        policy,
        employee,
        leave_type,
        start_date,
        exclude_pk,
    ):
        """
        Cuti sejenis yang pernah dipakai pegawai ini.

        Cakupannya ditentukan `per_event`, dan bedanya bukan detail:

        - **Per kejadian** (menikah, melahirkan, duka) → **seumur
          bekerja**. Yang ditanyakan "apakah ia pernah memakai hak ini",
          dan hak yang melekat pada kejadian tidak reset tiap Januari.
        - **Selain itu** (sakit, khusus, tanpa upah) → **tahun yang
          sama**. Riwayat sakit lima tahun lalu tidak membantu siapa pun
          memutuskan pengajuan hari ini, dan peringatan yang selalu
          menyala berhenti dibaca dalam sebulan.
        """
        if not policy.history_check:
            return [], 0, []

        from apps.hr.models import (
            LEAVE_BLOCKING_STATUSES,
            EmployeeLeave,
        )

        queryset = (
            EmployeeLeave.objects
            .filter(
                employee=employee,
                leave_type=leave_type,
                is_deleted=False,
                # Yang draft belum jadi apa-apa dan yang ditolak sudah
                # selesai; menampilkan keduanya sebagai "pernah
                # dipakai" membuat peringatannya salah dengan cara yang
                # merugikan pengajunya.
                status__in=LEAVE_BLOCKING_STATUSES,
            )
            .select_related("leave_type")
            .order_by("-start_date", "-pk")
        )

        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)

        if not policy.per_event and start_date is not None:
            queryset = queryset.filter(start_date__year=start_date.year)

        total = queryset.count()

        if not total:
            return [], 0, []

        history = [
            {
                "id": row.pk,
                "document_number": row.document_number or None,
                "leave_type": getattr(row.leave_type, "name", None),
                "leave_type_code": getattr(row.leave_type, "code", None),
                "event_date": (
                    row.start_date.isoformat()
                    if row.start_date
                    else None
                ),
                "end_date": (
                    row.end_date.isoformat() if row.end_date else None
                ),
                "days": (
                    str(row.total_days)
                    if row.total_days is not None
                    else None
                ),
                "status": row.status,
                "status_label": row.get_status_display(),
            }
            for row in queryset[:HISTORY_LIMIT]
        ]

        action = policy.history_action or LeaveHistoryAction.NONE

        level = {
            LeaveHistoryAction.BLOCK: RuleLevel.BLOCK,
            LeaveHistoryAction.REVIEW: RuleLevel.REVIEW,
        }.get(action, RuleLevel.WARNING)

        scope = (
            "seumur bekerja"
            if policy.per_event
            else f"tahun {start_date.year}"
            if start_date is not None
            else "tahun berjalan"
        )

        latest = history[0]

        message = (
            f"Pegawai pernah menggunakan "
            f"{getattr(leave_type, 'name', 'jenis cuti ini')} "
            f"{total}x ({scope}). Terakhir "
            f"{latest['event_date']}"
            + (f", {latest['days']} hari" if latest["days"] else "")
            + f", status {latest['status_label']}."
        )

        if level == RuleLevel.BLOCK:
            message = (
                f"{message} {policy.code} tidak mengizinkan jenis cuti "
                f"ini diambil lebih dari sekali."
            )
        else:
            message = (
                f"{message} Periksa apakah ini memang kejadian yang "
                f"berbeda — pengajuannya tidak ditahan."
            )

        return (
            history,
            total,
            [
                LeaveRuleFinding(
                    code="history",
                    level=level,
                    field="leave_type",
                    message=message,
                ),
            ],
        )


def evaluate_leave_rules(**kwargs) -> LeaveRuleReport:
    """
    Penilaian satuan, untuk pemanggil yang tidak memutar apa pun.

    Memo di `LeaveRuleEvaluator` baru berguna saat satu instance dipakai
    berkali-kali; membuat instance sekali pakai di sini menjaga
    pemanggilnya tetap satu baris.
    """
    return LeaveRuleEvaluator().evaluate(**kwargs)
