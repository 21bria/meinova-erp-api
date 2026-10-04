"""
Lapisan kebijakan BPJS.

Satu-satunya tugasnya: menjawab "iuran apa saja yang berlaku untuk
pegawai ini, pada periode ini" dan mengembalikannya sebagai **objek
berbentuk baris** — bentuk yang sama dengan `DeductionTemplateLine` di
mata mesin hitung.

**Tidak ada mesin hitung BPJS.** Yang mengalikan tarif dengan dasar,
menjepit plafon, memisahkan beban perusahaan, mengurangi dasar pajak,
dan membekukan hasilnya tetap `PayrollCalculationService` yang sudah
ada. Mesin kedua berarti dua tempat yang harus tetap sepakat tentang
hal yang sama, dan yang satu selalu ketinggalan.

Susunannya:

    aturan & kepesertaan (ORM, di sini)
            ↓
    objek berbentuk baris
            ↓
    mesin hitung generik (tidak menyentuh ORM)
            ↓
    PayrollRunComponent + snapshot
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from apps.payroll.models import (
    BpjsDailyBasicMethod,
    BpjsEnrollment,
    BpjsProgram,
    BpjsRule,
    PayrollBasis,
    PayrollComponentSource,
    PayrollFindingLevel,
)
from apps.payroll.services.calculation import plain


ZERO = Decimal("0.00")

#: Dipakai `PayrollRunComponent.reference_type`, dan lewat itu juga
#: yang menahan penghapusan aturan yang sudah dipakai payroll.
BPJS_REFERENCE_TYPE = "payroll.bpjs_rule"


@dataclass
class BpjsResolvedLine:
    """
    Aturan BPJS yang sudah diresolusi, berbentuk baris potongan.

    Atribut-atributnya persis yang dibaca `_deductions`. Sengaja
    **bukan** turunan `DeductionTemplateLine`: ia tidak pernah
    tersimpan, dan mewarisinya berarti sebuah baris yang tidak ada di
    database ikut membawa manager, constraint, dan `save()` yang tidak
    berlaku untuknya.
    """

    code: str
    name: str
    rate: Decimal

    #: Selalu basis resolver. Bukan `percent_of_basic`: dasar iuran
    #: sudah disusun lapisan kebijakan di `compose_base()`, dan basis
    #: lain membuat mesin hitung menyusun ulang dasarnya sendiri —
    #: seluruh komposisi (tunjangan yang disebut, `include_basic`)
    #: hilang tanpa satu pesan pun, karena angkanya tetap keluar.
    basis: str = PayrollBasis.PERCENT_OF_RESOLVED_BASE
    amount: Decimal = ZERO
    sequence: int = 1

    minimum_base: Decimal | None = None
    maximum_base: Decimal | None = None
    minimum_amount: Decimal | None = None
    maximum_amount: Decimal | None = None

    reduces_taxable: bool = False
    is_employer_cost: bool = False

    # Prorata masa kerja **tidak** dikenakan. Dasar iuran hari ini gaji
    # pokok menurut kontrak (keputusan #3A butir 4); kebijakan prorata
    # dasar iuran adalah #3B dan belum diputuskan.
    is_prorated: bool = False

    pk: int | None = None
    reference_type: str = BPJS_REFERENCE_TYPE
    source: str = PayrollComponentSource.BPJS

    #: Dasar yang sudah dikomposisi resolver. Mesin hitung memakainya
    #: apa adanya lewat basis `percent_of_resolved_base` di atas.
    resolved_base: Decimal = ZERO
    base_note: str = ""


@dataclass
class BpjsEmployeeFacts:
    """
    Fakta pegawai yang dibutuhkan dasar iuran, sudah dihitung `run.py`.

    Dioper masuk, bukan dibaca ulang: `payable_days` dan upah sehari
    lahir dari kebijakan payroll yang sudah diresolusi per baris, dan
    resolver yang menghitungnya sendiri akan jadi tempat kedua yang
    harus tetap sepakat dengan yang pertama.
    """

    is_daily: bool = False
    daily_rate: Decimal = ZERO
    paid_days: Decimal = ZERO


@dataclass
class BpjsContext:
    """
    Master BPJS yang dibaca **sekali per run**, bukan per pegawai.

    Run berisi 500 orang membaca program dan aturan yang sama 500 kali
    kalau tidak — pola yang sama dengan cache tingkat lembur di
    `run.py`.
    """

    programs: list = field(default_factory=list)
    rules_by_program: dict = field(default_factory=dict)
    base_codes_by_definition: dict = field(default_factory=dict)
    enrollments_by_employee: dict = field(default_factory=dict)
    known_allowance_codes: set = field(default_factory=set)
    risk_class_labels: dict = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.programs


class BpjsResolver:
    """
    Resolusi aturan dan kepesertaan BPJS untuk satu periode.
    """

    # ------------------------------------------------------------------
    # Pembacaan master — sekali per run
    # ------------------------------------------------------------------

    @classmethod
    def build_context(cls, *, employee_ids, anchor_date) -> BpjsContext:
        programs = list(
            BpjsProgram.objects
            .filter(is_deleted=False, is_active=True)
            .order_by("sequence", "code"),
        )

        if not programs:
            return BpjsContext()

        program_ids = [program.pk for program in programs]

        rules_by_program: dict = {}

        rules = (
            BpjsRule.objects
            .filter(
                program_id__in=program_ids,
                is_deleted=False,
                is_active=True,
                effective_from__lte=anchor_date,
            )
            .select_related("program", "company", "base_definition", "risk_class")
            .order_by("-effective_from", "id")
        )

        for rule in rules:
            if rule.effective_to is not None and rule.effective_to < anchor_date:
                continue

            rules_by_program.setdefault(rule.program_id, []).append(rule)

        definition_ids = {rule.base_definition_id for rule in rules}

        base_codes: dict = {}

        if definition_ids:
            from apps.payroll.models import BpjsBaseComponent

            for row in (
                BpjsBaseComponent.objects
                .filter(definition_id__in=definition_ids, is_deleted=False)
                .order_by("sequence", "allowance_code")
            ):
                base_codes.setdefault(row.definition_id, []).append(
                    row.allowance_code,
                )

        enrollments: dict = {}

        for row in (
            BpjsEnrollment.objects
            .filter(
                employee_id__in=list(employee_ids),
                program_id__in=program_ids,
                is_deleted=False,
                is_active=True,
                participates=True,
                enrolled_from__lte=anchor_date,
            )
        ):
            if row.enrolled_to is not None and row.enrolled_to < anchor_date:
                continue

            enrollments[(row.employee_id, row.program_id)] = row

        from apps.payroll.models import AllowanceTemplateLine

        known_codes = set(
            AllowanceTemplateLine.objects
            .filter(is_deleted=False)
            .values_list("code", flat=True),
        )

        from apps.payroll.models import BpjsRiskClass

        risk_labels = dict(
            BpjsRiskClass.objects
            .filter(is_deleted=False)
            .values_list("id", "code"),
        )

        return BpjsContext(
            programs=programs,
            rules_by_program=rules_by_program,
            base_codes_by_definition=base_codes,
            enrollments_by_employee=enrollments,
            known_allowance_codes=known_codes,
            risk_class_labels=risk_labels,
        )

    @staticmethod
    def _risk_label(context: BpjsContext, risk_class_id) -> str:
        if risk_class_id is None:
            return "(belum diisi)"

        return context.risk_class_labels.get(risk_class_id) or str(risk_class_id)

    # ------------------------------------------------------------------
    # Resolusi aturan
    # ------------------------------------------------------------------

    @staticmethod
    def resolve_rule(
        *,
        context: BpjsContext,
        program_id,
        company_id,
        uses_risk_class=False,
        risk_class_id=None,
    ):
        """
        Aturan yang berlaku: **perusahaan dulu, baru bawaan tenant**.

        Override perusahaan mengganti aturan secara utuh — tidak ada
        penggabungan per kolom, jadi selalu ada tepat satu aturan yang
        bisa disebut namanya. Tumpang tindih rentang sudah ditolak
        `BpjsRule.clean()`, jadi di sini tidak ada pilihan yang perlu
        ditebak.

        **Program berkelas risiko dicocokkan ketat.** Urutannya
        perusahaan+kelas persis, lalu global+kelas persis, lalu tidak
        ada. Tidak ada jatuh-tempo ke aturan tanpa kelas dan tidak ada
        pinjam-tarif dari kelas lain: tarif risiko yang salah kelas
        tetap menghasilkan angka yang kelihatan wajar, dan itu bentuk
        kesalahan yang tidak pernah ketahuan. Tidak ketemu berarti
        ERROR, sama seperti aturan yang memang belum ada.
        """
        candidates = context.rules_by_program.get(program_id) or []

        if uses_risk_class:
            if risk_class_id is None:
                return None

            for rule in candidates:
                if (
                    rule.company_id == company_id
                    and rule.risk_class_id == risk_class_id
                ):
                    return rule

            for rule in candidates:
                if (
                    rule.company_id is None
                    and rule.risk_class_id == risk_class_id
                ):
                    return rule

            return None

        for rule in candidates:
            if rule.company_id == company_id:
                return rule

        for rule in candidates:
            if rule.company_id is None:
                return rule

        return None

    # ------------------------------------------------------------------
    # Dasar iuran
    # ------------------------------------------------------------------

    @classmethod
    def compose_base(cls, *, rule, context: BpjsContext, earnings, facts=None):
        """
        Dasar iuran = gaji pokok kontraktual + komponen yang **disebut**.

        `earnings` adalah komponen penghasilan yang sudah dihitung mesin
        pada periode ini. Yang boleh masuk hanya dua sumber: `BASIC` dan
        `ALLOWANCE_TEMPLATE`. Lembur (`OVERTIME`) dan input variabel
        (`INPUT`) **tidak pernah jadi kandidat** — bukan disaring
        belakangan, tapi memang tidak pernah ikut dipertimbangkan. Itu
        yang membuat dasar iuran tidak ikut berayun tiap bulan mengikuti
        hal yang tidak ada hubungannya dengan upah yang dilaporkan.

        Mengembalikan `(dasar, keterangan, kode yang tidak dikenal)`.
        """
        definition = rule.base_definition

        facts = facts or BpjsEmployeeFacts()

        parts: list[tuple[str, Decimal]] = []

        if definition.include_basic:
            basic, basic_label = cls._basic_part(
                definition=definition, facts=facts, earnings=earnings,
            )

            if basic_label:
                parts.append((basic_label, basic))

        wanted = context.base_codes_by_definition.get(definition.pk) or []

        unknown: list[str] = []

        for code in wanted:
            if code not in context.known_allowance_codes:
                unknown.append(code)

            for component in earnings:
                if (
                    component.source == PayrollComponentSource.ALLOWANCE_TEMPLATE
                    and component.code == code
                ):
                    parts.append((code, Decimal(component.amount)))
                    break

        base = sum((amount for _, amount in parts), ZERO)

        note = " + ".join(label for label, _ in parts)

        return base, note, unknown

    @staticmethod
    def _basic_part(*, definition, facts, earnings):
        """
        Bagian "gaji pokok" dari dasar iuran.

        Pegawai bulanan memakai gaji pokok **menurut kontrak**
        (keputusan #3A butir 4). Pegawai harian tidak punya angka itu —
        kolomnya memang kosong — jadi dasarnya dibentuk dari upah sehari
        menurut cara yang **dikonfigurasi**, bukan menurut angka yang
        dipilihkan sistem.

        Cara `NONE` sengaja menghasilkan nol: itu perilaku hari ini, dan
        yang membuatnya tidak diam adalah peringatan `bpjs_base_zero`.
        """
        if not facts.is_daily:
            for component in earnings:
                if component.source == PayrollComponentSource.BASIC:
                    return Decimal(component.base_amount), "Gaji Pokok"

            return ZERO, ""

        method = definition.daily_basic_method
        rate = Decimal(facts.daily_rate or 0)

        if method == BpjsDailyBasicMethod.DAILY_RATE_X_FACTOR:
            factor = Decimal(definition.daily_basic_factor or 0)

            return rate * factor, f"Upah Harian x {plain(factor)}"

        if method == BpjsDailyBasicMethod.PAID_DAYS_X_DAILY_RATE:
            days = Decimal(facts.paid_days or 0)

            return rate * days, f"{plain(days)} Hari Dibayar x Upah Harian"

        # `NONE`. Tidak ada dasar harian yang diputuskan, jadi tidak ada
        # yang dikarang.
        return ZERO, ""

    # ------------------------------------------------------------------
    # Baris hasil resolusi
    # ------------------------------------------------------------------

    @classmethod
    def resolve_lines(
        cls,
        *,
        context: BpjsContext,
        employee_id,
        company_id,
        earnings,
        add_finding,
        facts=None,
    ) -> list[BpjsResolvedLine]:
        """
        Seluruh baris BPJS untuk satu pegawai.

        `add_finding(level=..., code=..., message=...)` dioper masuk,
        bukan dipanggil lewat import: temuan menempel pada baris run
        yang sedang dihitung, dan resolver tidak perlu tahu bentuk
        wadahnya.
        """
        if context.is_empty:
            return []

        lines: list[BpjsResolvedLine] = []

        sequence = 500

        for program in context.programs:
            enrollment = context.enrollments_by_employee.get(
                (employee_id, program.pk),
            )

            if enrollment is None:
                # Tidak terdaftar = tidak ikut. Keadaan normal yang sah,
                # dan **bukan** temuan: kepesertaan yang disimpulkan dari
                # ketiadaan data adalah cara memotong iuran dari orang
                # yang tidak pernah didaftarkan.
                continue

            rule = cls.resolve_rule(
                context=context,
                program_id=program.pk,
                company_id=company_id,
                uses_risk_class=program.uses_risk_class,
                risk_class_id=enrollment.risk_class_id,
            )

            if rule is None:
                # ERROR, bukan WARNING, dan bukan aturan nol yang
                # dikarang: peserta aktif yang iurannya nol karena
                # konfigurasinya belum ada adalah payroll yang salah dan
                # terlihat benar. Level ERROR membuat `assert_ready()`
                # menolak Submit maupun Finalize.
                scope = f"program BPJS {program.code}"

                if program.uses_risk_class:
                    # Menyebut kelasnya, karena aturan yang hilang di
                    # sini bukan "aturan JKK" melainkan "aturan JKK
                    # untuk kelas ini" — dan tanpa menyebutnya, operator
                    # melihat aturan JKK yang sudah ada lalu menyangka
                    # temuannya keliru.
                    label = cls._risk_label(context, enrollment.risk_class_id)
                    scope = f"{scope} kelas risiko {label}"

                add_finding(
                    level=PayrollFindingLevel.ERROR,
                    code="bpjs_rule_missing",
                    message=(
                        f"Pegawai terdaftar pada {scope} tapi belum ada "
                        f"aturan yang berlaku untuk periode ini. "
                        f"Lengkapi BPJS Rule lebih dulu."
                    ),
                )
                continue

            if not enrollment.membership_number:
                add_finding(
                    level=PayrollFindingLevel.WARNING,
                    code="bpjs_membership_missing",
                    message=(
                        f"Nomor kepesertaan BPJS {program.code} belum "
                        f"diisi. Iurannya tetap dihitung."
                    ),
                )

            base, note, unknown = cls.compose_base(
                rule=rule,
                context=context,
                earnings=earnings,
                facts=facts,
            )

            for code in unknown:
                add_finding(
                    level=PayrollFindingLevel.WARNING,
                    code="bpjs_base_component_unknown",
                    message=(
                        f"Komposisi dasar BPJS {program.code} menyebut "
                        f"komponen '{code}' yang tidak ada di master "
                        f"tunjangan mana pun. Komponen itu tidak ikut "
                        f"jadi dasar iuran."
                    ),
                )

            if base <= ZERO and rule.base_minimum is None:
                # Peserta aktif dengan dasar nol menghasilkan iuran nol
                # yang tidak terlihat salah di layar mana pun — bentuk
                # kegagalan yang persis dilarang keputusan #3A butir 2.
                # Paling sering terjadi pada pegawai harian, yang
                # `basic_salary`-nya memang nol.
                #
                # WARNING, bukan ERROR: perlakuan pegawai harian belum
                # diputuskan (#3B), jadi yang boleh dilakukan sekarang
                # hanya menolak diam — bukan menolak payroll-nya.
                add_finding(
                    level=PayrollFindingLevel.WARNING,
                    code="bpjs_base_zero",
                    message=(
                        f"Dasar iuran BPJS {program.code} nol, jadi "
                        f"iurannya nol. Periksa gaji pokok dan "
                        f"komposisi dasar iurannya."
                    ),
                )

            sequence += 1

            if rule.has_employee_side:
                lines.append(
                    cls._line(
                        rule=rule,
                        program=program,
                        base=base,
                        base_note=note,
                        sequence=sequence,
                        employer=False,
                    ),
                )

            if rule.has_employer_side:
                sequence += 1

                lines.append(
                    cls._line(
                        rule=rule,
                        program=program,
                        base=base,
                        base_note=note,
                        sequence=sequence,
                        employer=True,
                    ),
                )

        return lines

    @staticmethod
    def _line(*, rule, program, base, base_note, sequence, employer):
        return BpjsResolvedLine(
            code=f"BPJS-{program.code}-ER" if employer else f"BPJS-{program.code}",
            name=(
                f"{program.name} (Perusahaan)" if employer else program.name
            ),
            rate=(rule.employer_rate if employer else rule.employee_rate),
            sequence=sequence,
            minimum_base=rule.base_minimum,
            maximum_base=rule.base_maximum,
            minimum_amount=(
                rule.employer_minimum_amount
                if employer
                else rule.employee_minimum_amount
            ),
            maximum_amount=(
                rule.employer_maximum_amount
                if employer
                else rule.employee_maximum_amount
            ),
            # Sisi perusahaan tidak pernah mengurangi dasar pajak
            # pegawai — iuran yang tidak pernah dipotong dari seseorang
            # tidak bisa mengurangi pajaknya.
            reduces_taxable=(False if employer else rule.reduces_taxable),
            is_employer_cost=employer,
            pk=rule.pk,
            resolved_base=base,
            base_note=base_note,
        )
