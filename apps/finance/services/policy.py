"""
Mesin kebijakan akuntansi: kejadian → baris jurnal.

Yang dilakukannya persis satu hal: membaca `AccountingEvent.payload`,
mencocokkannya dengan aturan yang dikonfigurasi tenant, lalu menyusun
daftar baris jurnal. Ia **tidak** menyimpan apa pun dan tidak mengenal
satu pun model modul sumber — yang dibacanya dict, dan yang
dikembalikannya dict.

Pemisahan itu yang membuat `apps/finance` tidak pernah perlu
mengimpor `apps.payroll`, dan `apps/payroll` tidak pernah perlu
menyebut satu pun kode akun.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

from apps.core.services.master import BaseMasterService
from apps.finance import conditions
from apps.finance.models import (
    CORE_DIMENSIONS,
    ZERO,
    AccountingPolicy,
    AccountingPolicyLine,
    AccountingPolicyRule,
    PostingSide,
)
from apps.finance.services.mapping import (
    AccountMappingService,
    MappingContext,
)


@dataclass
class DraftLine:
    """Satu baris jurnal yang belum ditulis."""

    account_id: int
    side: str
    amount: Decimal
    description: str = ""
    core_dimensions: dict = field(default_factory=dict)
    extra_dimensions: dict = field(default_factory=dict)
    source_reference: str = ""
    metadata: dict = field(default_factory=dict)


class AccountingPolicyService(BaseMasterService):
    model = AccountingPolicy

    @staticmethod
    def list():
        return (
            AccountingPolicy.objects
            .filter(is_deleted=False)
            .select_related("company")
            .prefetch_related("rules__lines")
            .order_by("event_type", "code")
        )

    # ------------------------------------------------------------------
    # Pencarian kebijakan
    # ------------------------------------------------------------------

    @classmethod
    def resolve(cls, *, event_type: str, company_id: int, on_date: date):
        """
        Kebijakan yang berlaku, yang paling khusus menang.

        Kekhususannya cuma satu tingkat di sini — bercompany vs global —
        jadi tidak perlu skor: yang bercompany selalu menang. Kalau
        suatu saat kebijakan perlu bercakupan site juga, yang ditambah
        skor seperti `AccountMapping.specificity`, bukan rangkaian `if`.
        """
        candidates = (
            AccountingPolicy.objects
            .filter(
                is_deleted=False,
                is_active=True,
                event_type=event_type,
            )
            .prefetch_related("rules__lines")
            # Bercompany lebih dulu. NULL diurutkan terakhir oleh
            # PostgreSQL pada ASC, jadi `-company_id` justru menaruhnya
            # di depan — karena itu urutannya dibalik lewat `F`.
            .order_by("-company_id")
        )

        best = None

        for policy in candidates:
            if policy.company_id not in (None, company_id):
                continue

            if not policy.applies_on(on_date):
                continue

            if best is None:
                best = policy

                continue

            # Bercompany menang atas global.
            if policy.company_id is not None and best.company_id is None:
                best = policy

        return best

    # ------------------------------------------------------------------
    # Penerapan
    # ------------------------------------------------------------------

    @classmethod
    def build_lines(
        cls,
        *,
        policy: AccountingPolicy,
        payload: dict,
        company_id: int,
        on_date: date,
    ) -> list[DraftLine]:
        """
        Menjalankan seluruh aturan kebijakan terhadap payload.

        Aturan dijalankan **berurutan** dan semuanya dicoba, kecuali
        yang `stop_on_match`. Itu yang memungkinkan satu kejadian gaji
        menghasilkan belasan baris: satu aturan per jenis komponen,
        masing-masing menyumbang pasangan debit/kreditnya.
        """
        drafts: list[DraftLine] = []

        rules = sorted(
            (
                rule for rule in policy.rules.all()
                if not rule.is_deleted and rule.is_active
            ),
            key=lambda rule: rule.sequence,
        )

        if not rules:
            raise ValidationError({
                "policy": (
                    f"Kebijakan '{policy.code}' belum punya satu pun "
                    "aturan, jadi tidak ada jurnal yang bisa lahir "
                    "darinya."
                ),
            })

        for rule in rules:
            rows = cls._rows_for(rule=rule, payload=payload)

            for row in rows:
                if not conditions.evaluate(rule.conditions, row):
                    continue

                drafts.extend(
                    cls._lines_for(
                        rule=rule,
                        row=row,
                        company_id=company_id,
                        on_date=on_date,
                        policy=policy,
                    )
                )

                if rule.stop_on_match:
                    break

        return drafts

    @staticmethod
    def _rows_for(*, rule: AccountingPolicyRule, payload: dict) -> list[dict]:
        """
        Baris-baris yang dinilai aturan ini.

        Tanpa `iterate_over`, payload dinilai utuh sebagai satu baris.
        Dengan `iterate_over`, tiap elemen daftarnya dinilai sendiri —
        **dan payload induknya ikut disertakan** lewat `_parent`, supaya
        syarat sebuah komponen tetap bisa menyebut nilai di tingkat
        dokumen (perusahaannya, periodenya) tanpa harus disalin ke tiap
        elemen oleh modul sumber.
        """
        if not rule.iterate_over:
            return [payload]

        raw = conditions.read(payload, rule.iterate_over)

        if raw is conditions.MISSING or raw is None:
            # Daftar yang tidak ada = tidak ada baris. **Bukan error**:
            # kejadian gaji tanpa komponen lembur adalah kejadian yang
            # sah, dan menolaknya membuat setiap payroll run gagal
            # kecuali yang kebetulan lengkap.
            return []

        if not isinstance(raw, (list, tuple)):
            raise ValidationError({
                "iterate_over": (
                    f"Aturan '{rule.name}' menunjuk '{rule.iterate_over}' "
                    "sebagai daftar, tapi isinya bukan daftar."
                ),
            })

        rows = []

        for item in raw:
            if isinstance(item, dict):
                rows.append({**item, "_parent": payload})
            else:
                rows.append({"value": item, "_parent": payload})

        return rows

    @classmethod
    def _lines_for(
        cls,
        *,
        rule: AccountingPolicyRule,
        row: dict,
        company_id: int,
        on_date: date,
        policy: AccountingPolicy,
    ) -> list[DraftLine]:
        drafts: list[DraftLine] = []

        lines = sorted(
            (
                line for line in rule.lines.all()
                if not line.is_deleted and line.is_active
            ),
            key=lambda line: line.sequence,
        )

        for line in lines:
            amount = cls._amount(line=line, row=row, rule=rule)

            if amount is None:
                continue

            if amount == ZERO and line.skip_when_zero:
                continue

            if amount < ZERO:
                # Nilai negatif dibalik sisinya, bukan ditolak. Modul
                # sumber lazim mengirim koreksi sebagai angka negatif,
                # dan baris jurnal bernilai negatif ditolak constraint
                # database — jadi tanpa ini, satu koreksi menggagalkan
                # seluruh penerbitan jurnalnya.
                amount = -amount
                side = (
                    PostingSide.CREDIT
                    if line.side == PostingSide.DEBIT
                    else PostingSide.DEBIT
                )
            else:
                side = line.side

            core, extra = cls._dimensions(line=line, row=row)

            account_id = cls._account(
                line=line,
                row=row,
                core=core,
                company_id=company_id,
                on_date=on_date,
                policy=policy,
            )

            drafts.append(
                DraftLine(
                    account_id=account_id,
                    side=side,
                    amount=amount,
                    description=cls._description(line=line, row=row),
                    core_dimensions=core,
                    extra_dimensions=extra,
                    source_reference=str(
                        conditions.read(row, "reference") or ""
                    )[:255],
                    metadata={
                        "policy": policy.code,
                        "rule": rule.name,
                        "line": line.sequence,
                    },
                )
            )

        return drafts

    @staticmethod
    def _amount(*, line: AccountingPolicyLine, row: dict, rule) -> Decimal | None:
        raw = conditions.read(row, line.amount_source)

        if raw is conditions.MISSING:
            # Nilai yang tidak ada **bukan nol**. Membukukannya sebagai
            # nol akan menerbitkan jurnal yang seimbang dan salah —
            # sisi lawannya tetap terbit dengan angkanya sendiri, dan
            # jurnalnya jadi tidak seimbang, atau lebih buruk: seimbang
            # dengan angka yang lebih kecil dari seharusnya.
            raise ValidationError({
                "amount_source": (
                    f"Aturan '{rule.name}' mencari nilai di "
                    f"'{line.amount_source}', tapi kunci itu tidak ada "
                    "di data kejadian. Perbaiki kebijakannya atau minta "
                    "modul sumber mengirimkannya."
                ),
            })

        if raw is None:
            return None

        try:
            return Decimal(str(raw)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError, TypeError):
            raise ValidationError({
                "amount_source": (
                    f"Nilai di '{line.amount_source}' bukan angka "
                    f"({raw!r})."
                ),
            })

    @staticmethod
    def _dimensions(*, line: AccountingPolicyLine, row: dict):
        """
        Membaca dimensi dari payload menurut peta di baris kebijakan.

        Dipisah jadi inti dan tambahan di sini — yang pertama jadi kolom
        pada baris jurnal, yang kedua jadi baris dimensi. Pemanggilnya
        tidak perlu tahu bedanya.
        """
        core: dict = {}
        extra: dict = {}

        for code, path in (line.dimension_sources or {}).items():
            value = conditions.read(row, path)

            if value is conditions.MISSING or value in (None, ""):
                continue

            if code in CORE_DIMENSIONS:
                core[code] = value
            else:
                extra[code] = value

        return core, extra

    @staticmethod
    def _description(*, line: AccountingPolicyLine, row: dict) -> str:
        template = line.description_template

        if not template:
            return ""

        try:
            return template.format(**{
                key: value for key, value in row.items()
                if not isinstance(value, (dict, list))
            })[:255]
        except (KeyError, IndexError, ValueError):
            # Keterangan yang templatenya salah **tidak** menggagalkan
            # jurnal. Ia keterangan; angkanya yang penting, dan
            # menggagalkan penerbitan gara-gara satu kurung kurawal yang
            # salah ketik adalah harga yang tidak sepadan.
            return template[:255]

    @staticmethod
    def _account(
        *,
        line: AccountingPolicyLine,
        row: dict,
        core: dict,
        company_id: int,
        on_date: date,
        policy: AccountingPolicy,
    ) -> int:
        if line.account_id:
            return line.account_id

        selectors = {
            key: value
            for key, value in row.items()
            if not isinstance(value, (dict, list))
        }

        account = AccountMappingService.resolve(
            mapping_key=line.mapping_key,
            context=MappingContext(
                company_id=company_id,
                event_type=policy.event_type,
                location_id=core.get("location"),
                department_id=core.get("department"),
                cost_center_id=core.get("cost_center"),
                selectors=selectors,
                on_date=on_date,
            ),
        )

        return account.pk


class AccountingPolicyRuleService(BaseMasterService):
    model = AccountingPolicyRule

    @staticmethod
    def list():
        return (
            AccountingPolicyRule.objects
            .filter(is_deleted=False)
            .select_related("policy")
            .order_by("policy__code", "sequence")
        )

    @classmethod
    def prepare_create_data(cls, *, data, user=None, **kwargs):
        return cls._validate_conditions(data)

    @classmethod
    def prepare_update_data(cls, *, instance, data, user=None, **kwargs):
        return cls._validate_conditions(data)

    @staticmethod
    def _validate_conditions(data: dict) -> dict:
        """
        Bentuk syarat diperiksa saat disimpan, bukan saat dipakai.

        Salah ketik yang baru ketahuan waktu payroll run diposting
        muncul di layar orang yang tidak bisa memperbaikinya — dan pada
        saat itu yang gagal adalah penerbitan jurnal untuk seluruh
        perusahaan.
        """
        if "conditions" not in data:
            return data

        from apps.workflow.conditions import validate

        validate(data.get("conditions"))

        return data


class AccountingPolicyLineService(BaseMasterService):
    model = AccountingPolicyLine

    @staticmethod
    def list():
        return (
            AccountingPolicyLine.objects
            .filter(is_deleted=False)
            .select_related("rule", "rule__policy", "account")
            .order_by("rule__policy__code", "rule__sequence", "sequence")
        )
