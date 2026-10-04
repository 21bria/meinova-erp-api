"""
Kebijakan akuntansi `PAYROLL_POSTED` + pemetaan akunnya.

**Ini bukan lagi contoh.** Sampai PF-0E berkas ini memang berisi
kebijakan karangan — aturannya membaca `category`/`component_type`,
dua kunci yang tidak pernah dikirim normalizer payroll, dan satu-satunya
potongan yang dibukukannya adalah pajak. Kebijakan itu **diganti**, bukan
dipertahankan: konfigurasi yang cocok dengan payload yang tidak ada
tidak menerbitkan apa pun, dan konfigurasi yang setengah cocok
menerbitkan jurnal yang tidak seimbang.

Yang dibaca kebijakan ini kontrak `payroll.posting/v1` (PF-0C):
`payload["components"]` berisi baris beragregat dengan
`semantic`/`detail`/`program`, jumlah bertanda, satu referensi dokumen,
dan enam dimensi organisasi. Tidak ada nama pegawai, nomor pegawai,
nama komponen, atau teks bebas tenant di mana pun — lihat
`apps/payroll/services/accounting.py`.

Dua hal yang membedakannya dari kebijakan Finance lain:

* `auto_post = False`. Jurnal gaji terbit **DRAFT** dan melewati alur
  persetujuan Finance seperti jurnal manual. Yang memfinalisasi payroll
  bukan yang memposting jurnalnya.
* `stop_on_match = False` di seluruh aturan. Tiap baris payload harus
  dinilai oleh setiap aturan; satu baris yang menghentikan sisa aturan
  akan membuang sisi lawan ayatnya.

Tidak ada satu pun kode akun di aturannya. Yang ditunjuk baris kebijakan
peran akuntansi (`SALARY_EXPENSE`), dan `AccountMapping` yang
menerjemahkannya jadi akun. Kode akun di berkas ini muncul **hanya** di
peta pemetaan contoh di bawah, dan itu template COA contoh yang memang
boleh menyebut dirinya sendiri.
"""

from __future__ import annotations

from django.utils import timezone

from apps.finance.models import (
    Account,
    AccountMapping,
    AccountingPolicy,
    AccountingPolicyLine,
    AccountingPolicyRule,
    PostingSide,
)


EVENT_TYPE = "PAYROLL_POSTED"

DEBIT = PostingSide.DEBIT
CREDIT = PostingSide.CREDIT


# ----------------------------------------------------------------------
# Peran akuntansi → akun template
# ----------------------------------------------------------------------

#: `{kunci pemetaan: (kode akun template, nama pemetaan)}`.
#:
#: Kode akunnya menunjuk template COA contoh (`chart_of_accounts.py`),
#: dan itu satu-satunya tempat kunci peran bertemu kode akun: pemetaan
#: adalah **data**, dan data contoh boleh menyebut data contoh lain.
#: Tenant sungguhan mengganti seluruh barisnya dari layar Account
#: Mapping tanpa menyentuh satu baris kode pun.
#:
#: Template contoh belum punya akun lembur dan akun beban jaminan sosial
#: tersendiri, jadi keduanya menumpang akun yang paling dekat artinya.
#: Itu keputusan **template**, bukan keputusan mesin — kebijakannya
#: tetap memisahkan OVERTIME_EXPENSE dari SALARY_EXPENSE, jadi tenant
#: yang memekarkan bagan akunnya cukup mengarahkan ulang satu baris.
MAPPING_ACCOUNTS = {
    "SALARY_EXPENSE": ("6100", "Salary expense"),
    "ALLOWANCE_EXPENSE": ("6110", "Allowance expense"),
    "OVERTIME_EXPENSE": ("6100", "Overtime expense"),
    "OTHER_EARNING_EXPENSE": ("6900", "Other earning expense"),
    "EMPLOYER_SOCIAL_EXPENSE": ("6120", "Employer social contribution expense"),
    "EMPLOYER_BENEFIT_EXPENSE": ("6120", "Employer benefit expense"),
    "PAYROLL_PAYABLE": ("2130", "Payroll payable"),
    "INCOME_TAX_PAYABLE": ("2140", "Employee income tax payable"),
    "SOCIAL_SECURITY_PAYABLE": ("2150", "Social security payable"),
    "OTHER_DEDUCTION_PAYABLE": ("2160", "Other employee deduction payable"),
    "EMPLOYER_BENEFIT_PAYABLE": ("2160", "Employer benefit payable"),
}


# ----------------------------------------------------------------------
# Makna PF-0C → ayat jurnal
# ----------------------------------------------------------------------

#: `(urutan, semantic, keterangan, [(urutan baris, sisi, kunci peran)])`
#:
#: Sisi di sini mengikuti persamaan kontrol PF-0C persis: tiap makna
#: ber-sisi debit di sana mendapat satu baris debit di sini, tiap makna
#: ber-sisi kredit mendapat satu baris kredit, dan dua makna yang berdiri
#: di **kedua** sisi (kontribusi pemberi kerja) mendapat keduanya. Itu
#: yang membuat jurnalnya seimbang tanpa satu pun baris penyeimbang.
#:
#: `EARNING_REDUCTION` **mengkredit beban**, bukan menerbitkan utang.
#: Ketidakhadiran dan cuti tanpa upah bukan uang yang terutang kepada
#: siapa pun — ia gaji yang tidak pernah terbentuk, jadi yang benar
#: mengurangi bebannya. Mengalirkannya ke akun utang menciptakan saldo
#: yang tidak akan pernah dibayar dan tidak akan pernah nol.
#:
#: Pinjaman/kasbon belum dibedakan (M4 ditunda): PF-0C
#: mengklasifikasikannya `OTHER_EMPLOYEE_DEDUCTION`, dan di sini ia
#: mengkredit `OTHER_DEDUCTION_PAYABLE` bersama potongan lain. Makna
#: akuntansi **tidak** ditebak dari kode teks bebasnya.
RULES = [
    (
        10,
        "BASIC_SALARY",
        "Basic salary",
        "Payroll basic salary — {reference}",
        [(1, DEBIT, "SALARY_EXPENSE")],
    ),
    (
        20,
        "ALLOWANCE",
        "Allowance",
        "Payroll allowance {detail} — {reference}",
        [(1, DEBIT, "ALLOWANCE_EXPENSE")],
    ),
    (
        30,
        "OVERTIME",
        "Overtime",
        # Tanpa `{detail}`: lembur dari sumber `overtime` tidak punya
        # detail, dan yang lain berdetail `INPUT` — satu-satunya makna
        # PF-0C yang detailnya boleh kosong, jadi satu-satunya yang akan
        # meninggalkan spasi menggantung di keterangannya.
        "Payroll overtime — {reference}",
        [(1, DEBIT, "OVERTIME_EXPENSE")],
    ),
    (
        40,
        "OTHER_EARNING",
        "Other earning",
        "Payroll other earning {detail} — {reference}",
        [(1, DEBIT, "OTHER_EARNING_EXPENSE")],
    ),
    (
        50,
        "EARNING_REDUCTION",
        "Earning reduction",
        "Payroll earning reduction {detail} — {reference}",
        # Kredit **beban**, bukan utang. Lihat catatan di atas.
        [(1, CREDIT, "SALARY_EXPENSE")],
    ),
    (
        60,
        "EMPLOYEE_INCOME_TAX",
        "Employee income tax",
        "Payroll income tax — {reference}",
        [(1, CREDIT, "INCOME_TAX_PAYABLE")],
    ),
    (
        70,
        "EMPLOYEE_SOCIAL_DEDUCTION",
        "Employee social security deduction",
        "Payroll employee social security {program} — {reference}",
        [(1, CREDIT, "SOCIAL_SECURITY_PAYABLE")],
    ),
    (
        80,
        "OTHER_EMPLOYEE_DEDUCTION",
        "Other employee deduction",
        "Payroll other deduction {detail} — {reference}",
        [(1, CREDIT, "OTHER_DEDUCTION_PAYABLE")],
    ),
    (
        90,
        "EMPLOYER_SOCIAL_CONTRIBUTION",
        "Employer social security contribution",
        "Payroll employer social security {program} — {reference}",
        # Dua baris, dan keduanya wajib: iuran pemberi kerja adalah
        # beban perusahaan **dan** utang kepada penyelenggara. Ia tidak
        # pernah menyentuh gaji bersih pegawai — tidak ada baris net pay
        # di aturan ini.
        [
            (1, DEBIT, "EMPLOYER_SOCIAL_EXPENSE"),
            (2, CREDIT, "SOCIAL_SECURITY_PAYABLE"),
        ],
    ),
    (
        100,
        "OTHER_EMPLOYER_CONTRIBUTION",
        "Employer benefit contribution",
        "Payroll employer benefit {detail} — {reference}",
        [
            (1, DEBIT, "EMPLOYER_BENEFIT_EXPENSE"),
            (2, CREDIT, "EMPLOYER_BENEFIT_PAYABLE"),
        ],
    ),
    (
        110,
        "NET_PAY",
        "Net pay",
        "Payroll net pay — {reference}",
        [(1, CREDIT, "PAYROLL_PAYABLE")],
    ),
]


#: Keenam dimensi yang dibekukan PF-0C. `company` sengaja tidak ada: ia
#: cakupan kepala dokumen, dan satu jurnal selalu milik satu perusahaan.
DIMENSION_SOURCES = {
    "branch": "branch_id",
    "location": "location_id",
    "division": "division_id",
    "department": "department_id",
    "section": "section_id",
    "cost_center": "cost_center_id",
}


# ----------------------------------------------------------------------
# Peninggalan yang diganti
# ----------------------------------------------------------------------

#: Kunci pemetaan demo lama → kunci peran yang menggantikannya.
#:
#: Dipakai **memindahkan akunnya**, bukan sekadar menghapus: tenant demo
#: yang sempat mengarahkan `MAP-…-TAX_PAYABLE` ke akun pajaknya sendiri
#: tidak kehilangan pilihan itu — ia pindah ke `INCOME_TAX_PAYABLE`.
#: Baris pemetaan yang **bukan** milik seed ini (kodenya lain) tidak
#: disentuh sama sekali.
LEGACY_MAPPING_KEYS = {
    "SALARY_EXPENSE": "SALARY_EXPENSE",
    "ALLOWANCE_EXPENSE": "ALLOWANCE_EXPENSE",
    "BENEFIT_EXPENSE": "EMPLOYER_BENEFIT_EXPENSE",
    "PAYROLL_PAYABLE": "PAYROLL_PAYABLE",
    "TAX_PAYABLE": "INCOME_TAX_PAYABLE",
    "SOCIAL_SECURITY_PAYABLE": "SOCIAL_SECURITY_PAYABLE",
    "OTHER_DEDUCTION_PAYABLE": "OTHER_DEDUCTION_PAYABLE",
}


def legacy_policy_code(company) -> str:
    return f"POL-{company.code}-PAYROLL"


def legacy_mapping_code(company, key: str) -> str:
    return f"MAP-{company.code}-{key}"


def policy_code(company) -> str:
    return f"POL-{company.code}-PAYROLL-STD"


def mapping_code(company, key: str) -> str:
    return f"MAP-{company.code}-PAY-{key}"


# ----------------------------------------------------------------------
# Seed
# ----------------------------------------------------------------------


def seed_payroll_policy(*, company, user=None) -> dict:
    """
    Kebijakan `PAYROLL_POSTED` untuk satu perusahaan.

    **Aman diulang.** Jalan kedua tidak membuat satu pun baris: kebijakan
    yang kodenya sudah ada dilewati utuh beserta aturan dan barisnya, dan
    pemetaan yang kodenya sudah ada dilewati **tanpa ditimpa** — akun yang
    sudah diarahkan tenant tetap miliknya.

    Yang **diganti dengan sengaja** cuma baris demo yang memang milik seed
    ini sendiri (`POL-…-PAYROLL`, `MAP-…-<KUNCI LAMA>`): keduanya
    dinonaktifkan lewat soft delete supaya tidak berdiri sebagai kebijakan
    tandingan yang aktif, dan akunnya dibawa pindah ke kunci peran baru.
    """
    accounts = {
        row.code: row
        for row in Account.objects.filter(company=company, is_deleted=False)
    }

    retired = _retire_legacy(company=company, user=user)

    mapping_created = _seed_mappings(
        company=company,
        accounts=accounts,
        carried=retired["accounts"],
        user=user,
    )

    policy_result = _seed_policy(company=company)

    return {
        "mappings": mapping_created,
        "policies": policy_result["policies"],
        "rules": policy_result["rules"],
        "retired_policies": retired["policies"],
        "retired_mappings": retired["mappings"],
    }


#: Nama lama. Dipertahankan supaya pemanggil di luar berkas ini tidak
#: perlu diubah serentak — isinya sudah bukan contoh lagi.
seed_example_policy = seed_payroll_policy


def _retire_legacy(*, company, user=None) -> dict:
    """
    Menonaktifkan kebijakan & pemetaan demo yang ditulis seed versi lama.

    Soft delete, bukan hapus: `AccountingEvent.applied_policy` menunjuk
    kebijakan yang pernah dipakai, dan menghapusnya memutus jejak
    jurnal yang sudah terbit. Yang dibutuhkan cuma ia berhenti ikut
    dipilih — `AccountingPolicyService.resolve()` dan
    `AccountMappingService.candidates()` keduanya menyaring
    `is_deleted=False`.
    """
    now = timezone.now()

    stamp = {
        "is_deleted": True,
        "is_active": False,
        "deleted_at": now,
        "deleted_by": user,
    }

    carried: dict[str, Account] = {}
    mappings_retired = 0

    for legacy_key, new_key in LEGACY_MAPPING_KEYS.items():
        legacy = (
            AccountMapping.objects
            .filter(
                code=legacy_mapping_code(company, legacy_key),
                mapping_key=legacy_key,
                event_type=EVENT_TYPE,
                is_deleted=False,
            )
            .select_related("account")
            .first()
        )

        if legacy is None:
            continue

        # Akunnya dibawa pindah. Kalau dua kunci lama menunjuk kunci baru
        # yang sama, yang pertama menang — urutannya tetap (dict literal),
        # jadi hasilnya tidak bergantung urutan baris di database.
        carried.setdefault(new_key, legacy.account)

        AccountMapping.objects.filter(pk=legacy.pk).update(**stamp)

        mappings_retired += 1

    policies_retired = 0

    legacy_policy = AccountingPolicy.objects.filter(
        code=legacy_policy_code(company),
        event_type=EVENT_TYPE,
        is_deleted=False,
    ).first()

    if legacy_policy is not None:
        AccountingPolicyLine.objects.filter(
            rule__policy=legacy_policy, is_deleted=False,
        ).update(**stamp)

        AccountingPolicyRule.objects.filter(
            policy=legacy_policy, is_deleted=False,
        ).update(**stamp)

        AccountingPolicy.objects.filter(pk=legacy_policy.pk).update(**stamp)

        policies_retired = 1

    return {
        "accounts": carried,
        "mappings": mappings_retired,
        "policies": policies_retired,
    }


def _seed_mappings(*, company, accounts, carried, user=None) -> int:
    from apps.finance.services import AccountMappingService

    created = 0

    for key, (account_code, name) in MAPPING_ACCOUNTS.items():
        code = mapping_code(company, key)

        if AccountMapping.objects.filter(code=code, is_deleted=False).exists():
            continue

        # Akun yang dibawa dari pemetaan demo menang atas template:
        # tenant yang sudah mengarahkannya tidak diam-diam dikembalikan
        # ke akun contoh.
        account = carried.get(key) or accounts.get(account_code)

        if account is None:
            # Template COA-nya belum diseed untuk perusahaan ini.
            # Dilewati, bukan digagalkan — pemetaan yang hilang gagal
            # tertutup saat jurnalnya disusun, dengan pesan yang menyebut
            # kunci mana yang belum diarahkan.
            continue

        AccountMappingService.create(
            data={
                "code": code,
                "name": name,
                "mapping_key": key,
                "company": company,
                "event_type": EVENT_TYPE,
                # Kosong: kunci perannya sendiri yang membedakan. Tenant
                # yang perlu memecahnya per departemen atau per program
                # menambah baris yang **lebih** khusus, dan baris itu
                # menang lewat skor kekhususan.
                "selectors": {},
                "account": account,
            },
            user=user,
        )

        created += 1

    return created


def _seed_policy(*, company) -> dict:
    code = policy_code(company)

    if AccountingPolicy.objects.filter(code=code, is_deleted=False).exists():
        return {"policies": 0, "rules": 0}

    policy = AccountingPolicy.objects.create(
        code=code,
        name=f"Payroll Posting — {company.name}",
        description=(
            "Menerbitkan jurnal gaji dari kejadian PAYROLL_POSTED "
            "(kontrak payroll.posting/v1). Jurnalnya terbit sebagai "
            "draft dan menunggu persetujuan Finance."
        ),
        company=company,
        event_type=EVENT_TYPE,
        journal_type="automatic",
        # Inti PF-0E. Yang memfinalisasi payroll tidak memposting jurnal.
        auto_post=False,
    )

    rules = 0

    for sequence, semantic, name, description, lines in RULES:
        rule = AccountingPolicyRule.objects.create(
            policy=policy,
            sequence=sequence,
            name=name,
            conditions={"field": "semantic", "op": "eq", "value": semantic},
            iterate_over="components",
            # **Wajib False.** Setiap baris payload harus dinilai oleh
            # setiap aturan; menghentikan evaluasi pada baris yang cocok
            # akan membuang sisi lawan ayatnya.
            stop_on_match=False,
        )

        for line_sequence, side, mapping_key in lines:
            AccountingPolicyLine.objects.create(
                rule=rule,
                sequence=line_sequence,
                side=side,
                mapping_key=mapping_key,
                amount_source="amount",
                # Hanya kolom terkendali: makna, detail, program, dan
                # nomor dokumen run. Tidak ada nama pegawai, nomor
                # pegawai, rekening, NPWP, nomor BPJS, nama komponen,
                # atau teks bebas tenant.
                description_template=description,
                dimension_sources=dict(DIMENSION_SOURCES),
            )

        rules += 1

    return {"policies": 1, "rules": rules}
