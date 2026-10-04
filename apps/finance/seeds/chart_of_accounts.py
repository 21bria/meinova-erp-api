"""
Bagan akun contoh — **template, bukan aturan**.

§3 menyebutnya eksplisit: template COA boleh ada, tapi ia bukan bagian
dari logika akuntansi inti. Tidak satu baris kode pun di
`apps/finance` menyebut satu pun kode di berkas ini. Menghapus
seluruhnya dan menyusun bagan akun sendiri dari layar menghasilkan
sistem yang berjalan sama persis.

Isinya sengaja **netral lintas industri**: tidak ada "Beban Pengupasan
Lapisan Penutup" untuk tambang, tidak ada "Harga Pokok Penjualan Ritel".
Yang ada golongan yang berlaku di mana saja, dan tenant menambahkan
cabangnya sendiri di bawahnya.

Kodenya empat digit dengan kelipatan seribu per golongan — konvensi
yang paling banyak dikenal, dan yang paling mudah diganti seluruhnya
karena tidak ada yang bergantung padanya.
"""

from __future__ import annotations

from apps.finance.models import AccountType
from apps.finance.services import AccountService


# (kode, nama, golongan, kategori, boleh posting)
#
# Susunannya dinyatakan lewat indentasi kode: "1100" jadi anak "1000"
# karena disebut sesudahnya di daftar dan induknya ditulis di kolom
# terakhir. Ditulis eksplisit, bukan disimpulkan dari awalan kode —
# menyimpulkan hierarki dari kode berarti tenant yang memakai
# penomoran lain kehilangan susunannya.
TEMPLATE = [
    # kode, nama, tipe, kategori, posting?, induk
    ("1000", "Assets", AccountType.ASSET, "", False, None),
    ("1100", "Current Assets", AccountType.ASSET, "current_asset", False, "1000"),
    ("1110", "Cash on Hand", AccountType.ASSET, "current_asset", True, "1100"),
    ("1120", "Cash in Bank", AccountType.ASSET, "current_asset", True, "1100"),
    ("1130", "Accounts Receivable", AccountType.ASSET, "current_asset", True, "1100"),
    ("1140", "Other Receivables", AccountType.ASSET, "current_asset", True, "1100"),
    ("1150", "Inventory", AccountType.ASSET, "current_asset", True, "1100"),
    ("1160", "Prepaid Expenses", AccountType.ASSET, "current_asset", True, "1100"),
    ("1170", "Prepaid Taxes", AccountType.ASSET, "current_asset", True, "1100"),
    ("1200", "Non-Current Assets", AccountType.ASSET, "fixed_asset", False, "1000"),
    ("1210", "Property, Plant & Equipment", AccountType.ASSET, "fixed_asset", True, "1200"),
    ("1220", "Accumulated Depreciation", AccountType.ASSET, "fixed_asset", True, "1200"),
    ("1230", "Intangible Assets", AccountType.ASSET, "intangible_asset", True, "1200"),

    ("2000", "Liabilities", AccountType.LIABILITY, "", False, None),
    ("2100", "Current Liabilities", AccountType.LIABILITY, "current_liability", False, "2000"),
    ("2110", "Accounts Payable", AccountType.LIABILITY, "current_liability", True, "2100"),
    ("2120", "Accrued Expenses", AccountType.LIABILITY, "current_liability", True, "2100"),
    # Tiga akun yang dipakai integrasi Payroll nanti. Ditaruh di
    # template supaya contoh kebijakan punya sasaran; namanya tetap
    # umum, dan pemetaannya tetap lewat Account Mapping.
    ("2130", "Payroll Payable", AccountType.LIABILITY, "current_liability", True, "2100"),
    ("2140", "Tax Payable", AccountType.LIABILITY, "current_liability", True, "2100"),
    ("2150", "Social Security Payable", AccountType.LIABILITY, "current_liability", True, "2100"),
    ("2160", "Other Payables", AccountType.LIABILITY, "current_liability", True, "2100"),
    ("2200", "Non-Current Liabilities", AccountType.LIABILITY, "non_current_liability", False, "2000"),
    ("2210", "Long-Term Debt", AccountType.LIABILITY, "non_current_liability", True, "2200"),

    ("3000", "Equity", AccountType.EQUITY, "", False, None),
    ("3100", "Share Capital", AccountType.EQUITY, "equity", True, "3000"),
    ("3200", "Retained Earnings", AccountType.EQUITY, "equity", True, "3000"),
    ("3300", "Current Year Result", AccountType.EQUITY, "equity", True, "3000"),

    ("4000", "Revenue", AccountType.REVENUE, "", False, None),
    ("4100", "Operating Revenue", AccountType.REVENUE, "operating_revenue", True, "4000"),
    ("4900", "Other Income", AccountType.REVENUE, "other_revenue", True, "4000"),

    ("5000", "Cost of Sales", AccountType.EXPENSE, "", False, None),
    ("5100", "Direct Material", AccountType.EXPENSE, "cost_of_sales", True, "5000"),
    ("5200", "Direct Labour", AccountType.EXPENSE, "cost_of_sales", True, "5000"),
    ("5300", "Manufacturing Overhead", AccountType.EXPENSE, "cost_of_sales", True, "5000"),

    ("6000", "Operating Expenses", AccountType.EXPENSE, "", False, None),
    ("6100", "Salary Expense", AccountType.EXPENSE, "operating_expense", True, "6000"),
    ("6110", "Allowance Expense", AccountType.EXPENSE, "operating_expense", True, "6000"),
    ("6120", "Employee Benefit Expense", AccountType.EXPENSE, "operating_expense", True, "6000"),
    ("6200", "Office Expense", AccountType.EXPENSE, "operating_expense", True, "6000"),
    ("6300", "Travel Expense", AccountType.EXPENSE, "operating_expense", True, "6000"),
    ("6400", "Depreciation Expense", AccountType.EXPENSE, "operating_expense", True, "6000"),
    ("6900", "Other Operating Expense", AccountType.EXPENSE, "operating_expense", True, "6000"),

    ("7000", "Other Income & Expense", AccountType.EXPENSE, "", False, None),
    ("7100", "Interest Expense", AccountType.EXPENSE, "other_expense", True, "7000"),
    ("7200", "Foreign Exchange Gain/Loss", AccountType.EXPENSE, "other_expense", True, "7000"),

    ("8000", "Tax", AccountType.EXPENSE, "", False, None),
    ("8100", "Income Tax Expense", AccountType.EXPENSE, "tax_expense", True, "8000"),
]


def seed_chart_of_accounts(*, company, user=None) -> dict:
    """
    Menyusun bagan akun contoh untuk satu perusahaan.

    Aman diulang: akun yang kodenya sudah ada **dilewati**, tidak
    ditimpa. Tenant yang sudah menyunting nama perkiraannya tidak boleh
    kehilangan suntingannya karena seseorang menjalankan seed lagi.
    """
    from apps.finance.models import Account

    existing = {
        row.code: row
        for row in Account.objects.filter(
            company=company, is_deleted=False,
        )
    }

    created = 0
    skipped = 0

    for code, name, account_type, category, posting, parent_code in TEMPLATE:
        if code in existing:
            skipped += 1

            continue

        parent = existing.get(parent_code) if parent_code else None

        if parent_code and parent is None:
            # Induknya belum ada — bisa terjadi kalau daftar di atas
            # disunting dan urutannya terbalik. Dilewati beserta
            # laporannya, bukan dibuat sebagai akun akar: akun yang
            # diam-diam naik ke akar merusak seluruh laporan
            # berhierarki, dan naiknya tidak terlihat di layar mana pun.
            skipped += 1

            continue

        account = AccountService.create(
            data={
                "company": company,
                "code": code,
                "name": name,
                "parent": parent,
                "account_type": account_type,
                "account_category": category,
                "posting_allowed": posting,
                "sort_order": int(code),
            },
            user=user,
        )

        existing[code] = account

        created += 1

    return {"created": created, "skipped": skipped}
