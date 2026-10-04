"""
Lapisan integrasi akuntansi: kejadian, kebijakan, dan pemetaan akun.

Inilah yang membuat kalimat ini tidak pernah muncul di modul mana pun:

    if source_module == "payroll":
        debit = salary_expense_account

Modul sumber mengirim **apa yang terjadi** (`AccountingEvent`), dan
tenant menentukan **jurnal apa yang lahir darinya** (`AccountingPolicy`
→ `AccountingPolicyLine` → `AccountMapping`). Payroll tidak pernah
menyebut satu pun kode akun, dan Finance tidak pernah mengenal satu pun
model payroll.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .choices import AccountingEventStatus, PostingSide


class AccountingEvent(BaseModel):
    """
    Satu kejadian bisnis yang berdampak akuntansi.

    `idempotency_key` adalah inti berkas ini. Ia unik, dan karena itu
    kejadian yang sama — dikirim ulang karena retry Celery, karena
    operator menekan tombol dua kali, atau karena job terjadwal berjalan
    dobel — **tidak bisa** menerbitkan jurnal kedua. Penjagaannya di
    database, bukan di kode: kode yang memeriksa dulu lalu menulis
    kemudian punya jendela di antaranya, dan dua proses bersamaan
    keduanya akan melihat "belum ada".
    """

    event_type = models.CharField(
        max_length=80,
        db_index=True,
        help_text=(
            "Nama kejadian, mis. PAYROLL_POSTED. Bebas — Finance tidak "
            "punya daftar tertutup; yang mengenalinya kebijakan "
            "akuntansi milik tenant."
        ),
    )

    source_module = models.CharField(max_length=50)
    source_type = models.CharField(max_length=80, blank=True, default="")
    source_id = models.CharField(max_length=80, blank=True, default="")
    source_reference = models.CharField(max_length=255, blank=True, default="")

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="accounting_events",
    )

    event_date = models.DateField()

    # Data ternormalisasi dari modul sumber. Bentuknya kontrak antara
    # modul itu dan kebijakan yang dikonfigurasi tenant — Finance tidak
    # menafsirkan isinya, ia cuma menilainya terhadap syarat kebijakan
    # dan membaca nilai yang ditunjuk baris kebijakan.
    payload = models.JSONField(default=dict, blank=True)

    idempotency_key = models.CharField(
        max_length=255,
        help_text=(
            "Penanda unik kejadian. Modul sumber yang menyusunnya, dan "
            "ia harus sama persis kalau kejadiannya sama — mis. "
            "`payroll:payroll_run:5163:posted`."
        ),
    )

    status = models.CharField(
        max_length=20,
        choices=AccountingEventStatus.choices,
        default=AccountingEventStatus.PENDING,
        db_index=True,
    )

    processed_at = models.DateTimeField(null=True, blank=True)

    generated_journal = models.ForeignKey(
        "finance.Journal",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="source_events",
    )

    applied_policy = models.ForeignKey(
        "finance.AccountingPolicy",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )

    # PF-0G. Kejadian yang menggantikan kejadian ini — diisi **hanya**
    # oleh layanan supersesi tepercaya, dan hanya untuk proyeksi yang
    # belum diposting. Kejadian yang jurnalnya sudah masuk buku besar
    # tidak pernah digantikan: sejarahnya dikoreksi lewat pembalikan
    # Finance, bukan dengan mencabut provenance-nya.
    superseded_by = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="supersedes",
    )

    attempts = models.PositiveSmallIntegerField(default=0)

    error_message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "finance_accounting_event"

        ordering = ["-event_date", "-id"]

        constraints = [
            # **Satu-satunya hal yang mencegah posting ganda.** Tanpa
            # kondisi `is_deleted` ia akan menolak kejadian yang
            # kembarannya sudah dibatalkan; dengan kondisi itu,
            # membatalkan sebuah kejadian berarti mengizinkannya dikirim
            # ulang — dan itu memang jalan keluar yang benar untuk
            # kejadian yang jurnalnya salah.
            models.UniqueConstraint(
                fields=["idempotency_key"],
                condition=Q(is_deleted=False),
                name="uniq_active_finance_event_idempotency",
            ),
        ]

        indexes = [
            models.Index(
                fields=["status", "event_date"],
                name="idx_fin_event_status_date",
            ),
            models.Index(
                fields=["source_module", "source_type", "source_id"],
                name="idx_fin_event_source",
            ),
            models.Index(
                fields=["company", "event_type", "event_date"],
                name="idx_fin_event_co_type_date",
            ),
        ]

    def clean(self):
        super().clean()

        # PF-0G. Kejadian tidak menggantikan dirinya sendiri.
        if self.pk and self.superseded_by_id == self.pk:
            raise ValidationError(
                {
                    "superseded_by": (
                        "Kejadian tidak bisa menggantikan dirinya sendiri."
                    ),
                },
            )

    def __str__(self) -> str:
        return f"{self.event_type} #{self.source_id}"


class AccountingPolicy(BaseModel):
    """
    Aturan penerbitan jurnal untuk satu jenis kejadian.

    Cakupannya berjenjang lewat `company`: baris tanpa perusahaan
    berlaku untuk semua, baris bercompany menang atasnya. Pola yang
    sama persis dengan `WorkflowDefinition` dan `NumberingSequence` —
    **kosong berarti "berlaku umum", bukan "tidak berlaku"**, dan itu
    jebakan yang sudah tiga kali muncul di codebase ini.
    """

    code = models.CharField(max_length=60)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="accounting_policies",
        help_text="Kosong = berlaku untuk semua perusahaan di tenant ini.",
    )

    event_type = models.CharField(max_length=80, db_index=True)

    journal_type = models.CharField(
        max_length=20,
        default="automatic",
        help_text="Jenis jurnal yang diterbitkan kebijakan ini.",
    )

    # **Bawaannya True, dan itu keharusan.** Seluruh kebijakan yang sudah
    # ada lahir sebelum kolom ini dan memang membukukan langsung; kolom
    # baru yang bawaannya False akan mengubah perilaku mereka diam-diam
    # pada migrasi yang tidak menyebut satu pun kebijakan.
    #
    # Yang mematikannya adalah **kebijakan**, bukan modul sumbernya.
    # Tanda di payload, tanda di kejadian, atau `if source_module ==
    # "payroll"` sama-sama memindahkan keputusan akuntansi ke tempat
    # yang tidak dilihat orang keuangan dan tidak bisa mereka ubah.
    auto_post = models.BooleanField(
        default=True,
        help_text=(
            "Aktif = jurnal yang lahir dari kejadian ini langsung "
            "dibukukan ke buku besar. Nonaktif = jurnalnya terbit "
            "sebagai DRAFT dan menunggu alur persetujuan Finance."
        ),
    )

    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "finance_accounting_policy"

        ordering = ["event_type", "code"]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_finance_policy_code",
            ),
        ]

        indexes = [
            models.Index(
                fields=["event_type", "company"],
                name="idx_fin_policy_event_company",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def applies_on(self, value) -> bool:
        if self.effective_from and value < self.effective_from:
            return False

        if self.effective_to and value > self.effective_to:
            return False

        return True

    def clean(self):
        super().clean()

        if (
            self.effective_from
            and self.effective_to
            and self.effective_to < self.effective_from
        ):
            raise ValidationError({
                "effective_to": "Tanggal akhir berlaku sebelum tanggal mulai.",
            })


class AccountingPolicyRule(BaseModel):
    """
    Satu cabang di dalam sebuah kebijakan.

    `conditions` memakai dialek yang sama persis dengan
    `WorkflowStep.condition` dan `visible_when` di schema UI —
    `{field, op, value}` digabung `all`/`any`/`not`. Satu dialek untuk
    seluruh sistem: orang keuangan yang pernah menulis syarat step
    approval tidak perlu mempelajari tata bahasa kedua.

    **Arah kegagalannya dibalik dari milik workflow, dan itu sengaja.**
    Di workflow, syarat yang tidak bisa dinilai dianggap **terpenuhi** —
    step approval yang hilang lebih berbahaya daripada step tambahan. Di
    sini kebalikannya: syarat yang tidak bisa dinilai berarti **tidak
    cocok**, karena aturan yang cocok karena salah ketik akan
    membukukan uang ke akun yang salah, dan tidak ada satu pun angka
    yang terlihat janggal sesudahnya. Lihat `apps/finance/conditions.py`.
    """

    policy = models.ForeignKey(
        AccountingPolicy,
        on_delete=models.CASCADE,
        related_name="rules",
    )

    sequence = models.PositiveSmallIntegerField(default=1)

    name = models.CharField(max_length=200)

    conditions = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Kosong = selalu cocok. Dinilai terhadap satu baris payload "
            "kejadian."
        ),
    )

    # Kejadian besar membawa banyak baris (satu per komponen gaji, satu
    # per item barang). Kunci ini menunjuk daftar di dalam payload yang
    # harus dijalankan satu per satu; kosong = payload dinilai sebagai
    # satu baris tunggal.
    iterate_over = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text=(
            "Kunci daftar di dalam payload yang dijalankan per baris, "
            "mis. `components`. Kosong = payload dinilai utuh."
        ),
    )

    stop_on_match = models.BooleanField(
        default=False,
        help_text=(
            "Aktif = aturan sesudahnya tidak dicoba lagi untuk baris "
            "yang cocok di sini."
        ),
    )

    class Meta:
        db_table = "finance_accounting_policy_rule"

        ordering = ["policy_id", "sequence"]

        constraints = [
            models.UniqueConstraint(
                fields=["policy", "sequence"],
                condition=Q(is_deleted=False),
                name="uniq_active_finance_policy_rule_seq",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class AccountingPolicyLine(BaseModel):
    """
    Cetakan satu baris jurnal.

    Akunnya **tidak** ditunjuk langsung kalau bisa dihindari: yang
    ditunjuk `mapping_key` — peran akuntansinya ("SALARY_EXPENSE") —
    dan `AccountMapping` yang menerjemahkannya jadi akun untuk
    perusahaan, site, atau kategori yang bersangkutan. `account`
    langsung tetap disediakan untuk kasus yang memang tidak bercabang;
    salah satunya wajib diisi.
    """

    rule = models.ForeignKey(
        AccountingPolicyRule,
        on_delete=models.CASCADE,
        related_name="lines",
    )

    sequence = models.PositiveSmallIntegerField(default=1)

    side = models.CharField(max_length=10, choices=PostingSide.choices)

    mapping_key = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text=(
            "Peran akuntansi yang dicari di Account Mapping, mis. "
            "SALARY_EXPENSE."
        ),
    )

    account = models.ForeignKey(
        "finance.Account",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="policy_lines",
        help_text="Akun langsung, untuk kasus yang tidak bercabang.",
    )

    amount_source = models.CharField(
        max_length=120,
        help_text=(
            "Jalur nilai di dalam payload, boleh menembus titik "
            "(`employer.bpjs_health`)."
        ),
    )

    description_template = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text=(
            "Keterangan baris. `{kunci}` diganti nilai dari payload."
        ),
    )

    # Peta `{kode dimensi: jalur payload}`. Inilah yang membawa
    # company/site/department/cost center dari dokumen sumber ke baris
    # jurnalnya — tanpa Finance mengenal bentuk dokumen itu.
    dimension_sources = models.JSONField(default=dict, blank=True)

    # Baris yang nilainya nol tidak dibukukan. Bawaannya membuang,
    # karena kejadian nyata penuh komponen bernilai nol (tunjangan yang
    # tidak berlaku bulan ini) dan menerbitkannya menghasilkan jurnal
    # berisi dua puluh baris kosong yang tidak terbaca siapa pun.
    skip_when_zero = models.BooleanField(default=True)

    class Meta:
        db_table = "finance_accounting_policy_line"

        ordering = ["rule_id", "sequence"]

        constraints = [
            models.UniqueConstraint(
                fields=["rule", "sequence"],
                condition=Q(is_deleted=False),
                name="uniq_active_finance_policy_line_seq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.side} {self.mapping_key or self.account_id}"

    def clean(self):
        super().clean()

        if not self.mapping_key and not self.account_id:
            raise ValidationError({
                "mapping_key": (
                    "Isi salah satu: kunci pemetaan akun, atau akun "
                    "langsung. Baris tanpa keduanya tidak bisa "
                    "diterbitkan."
                ),
            })

        if self.mapping_key:
            self.mapping_key = self.mapping_key.strip().upper()


class AccountMapping(BaseModel):
    """
    Penerjemah `mapping_key` menjadi akun.

    **Pemenangnya ditentukan skor kekhususan, bukan urutan baris.**
    Pola yang sama dengan `WorkflowDefinition.specificity`: baris yang
    menyebut lebih banyak syarat menang atas baris yang lebih umum,
    tanpa siapa pun perlu menyusun prioritas manual. Bobotnya
    diturunkan dari jumlah syarat yang benar-benar diisi, dihitung
    `AccountMappingService` dan disimpan supaya pengurutannya terjadi
    di database.

    **Seri sama kekhususan ditolak, bukan dipilih salah satunya.** Dua
    baris yang sama-sama cocok dan sama-sama khusus berarti konfigurasi
    yang ambigu, dan memilih salah satunya lewat urutan `id` membuat
    uang mendarat di akun yang ditentukan kebetulan. `AccountMappingService.
    resolve()` melempar; §29 menyebutnya "ambiguous mapping fails safely".
    """

    code = models.CharField(max_length=60)
    name = models.CharField(max_length=200)

    mapping_key = models.CharField(max_length=80, db_index=True)

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="account_mappings",
        help_text="Kosong = berlaku untuk semua perusahaan.",
    )

    event_type = models.CharField(
        max_length=80,
        blank=True,
        default="",
        help_text="Kosong = berlaku untuk semua jenis kejadian.",
    )

    # Syarat bebas terhadap konteks kejadian, mis.
    # `{"component_type": "BASIC_SALARY"}`. Cocok kalau **setiap**
    # pasangan di sini ada dan sama di konteksnya; konteks boleh
    # membawa kunci lain.
    selectors = models.JSONField(default=dict, blank=True)

    # Penyempit organisasi. Kolom, bukan bagian `selectors`, karena
    # ketiganya dipakai menyaring di database saat kandidat dikumpulkan
    # — dan menyaring di Python berarti memuat seluruh tabel pemetaan
    # untuk setiap baris jurnal yang diterbitkan.
    location = models.ForeignKey(
        "administration.Location", on_delete=models.CASCADE,
        null=True, blank=True, related_name="account_mappings",
    )
    department = models.ForeignKey(
        "administration.Department", on_delete=models.CASCADE,
        null=True, blank=True, related_name="account_mappings",
    )
    cost_center = models.ForeignKey(
        "administration.CostCenter", on_delete=models.CASCADE,
        null=True, blank=True, related_name="account_mappings",
    )

    account = models.ForeignKey(
        "finance.Account",
        on_delete=models.PROTECT,
        related_name="mappings",
    )

    specificity = models.PositiveSmallIntegerField(
        default=0,
        editable=False,
        help_text="Dihitung sistem dari jumlah syarat yang diisi.",
    )

    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "finance_account_mapping"

        ordering = ["mapping_key", "-specificity", "code"]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_finance_account_mapping_code",
            ),
            # Dua baris dengan syarat organisasi yang persis sama untuk
            # kunci yang sama akan berskor sama, dan pemenangnya jadi
            # soal urutan `id`. `selectors` tidak bisa ikut ke dalam
            # constraint (JSON tidak punya urutan kunci yang stabil);
            # yang menangkap sisanya `AccountMappingService.
            # detect_conflicts()`.
            models.UniqueConstraint(
                fields=[
                    "mapping_key",
                    "company",
                    "event_type",
                    "location",
                    "department",
                    "cost_center",
                    "selectors",
                ],
                condition=Q(is_deleted=False),
                name="uniq_active_finance_mapping_scope",
            ),
        ]

        indexes = [
            models.Index(
                fields=["mapping_key", "company", "event_type"],
                name="idx_fin_mapping_lookup",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.mapping_key} → {self.account_id}"

    def applies_on(self, value) -> bool:
        if self.effective_from and value < self.effective_from:
            return False

        if self.effective_to and value > self.effective_to:
            return False

        return True

    def clean(self):
        super().clean()

        if self.mapping_key:
            self.mapping_key = self.mapping_key.strip().upper()

        errors: dict[str, str] = {}

        if not isinstance(self.selectors, dict):
            errors["selectors"] = "Syarat harus berbentuk objek kunci–nilai."

        if (
            self.effective_from
            and self.effective_to
            and self.effective_to < self.effective_from
        ):
            errors["effective_to"] = (
                "Tanggal akhir berlaku sebelum tanggal mulai."
            )

        if self.account_id and self.company_id:
            if self.account.company_id != self.company_id:
                errors["account"] = (
                    "Akun yang dipilih milik perusahaan lain."
                )

        if self.account_id and not self.account.posting_allowed:
            errors["account"] = (
                f"'{self.account.code}' adalah akun grup dan tidak "
                "menerima jurnal."
            )

        if errors:
            raise ValidationError(errors)
