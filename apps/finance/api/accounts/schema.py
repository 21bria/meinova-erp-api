"""Schema UI Chart of Accounts."""

from apps.framework.builders import action, field, tabs, ui


ACCOUNT_TYPE_OPTIONS = [
    {"label": "Asset", "value": "asset"},
    {"label": "Liability", "value": "liability"},
    {"label": "Equity", "value": "equity"},
    {"label": "Revenue", "value": "revenue"},
    {"label": "Expense", "value": "expense"},
]

ACCOUNT_CATEGORY_OPTIONS = [
    {"label": "Current Asset", "value": "current_asset"},
    {"label": "Non-Current Asset", "value": "non_current_asset"},
    {"label": "Fixed Asset", "value": "fixed_asset"},
    {"label": "Intangible Asset", "value": "intangible_asset"},
    {"label": "Other Asset", "value": "other_asset"},
    {"label": "Current Liability", "value": "current_liability"},
    {"label": "Non-Current Liability", "value": "non_current_liability"},
    {"label": "Other Liability", "value": "other_liability"},
    {"label": "Equity", "value": "equity"},
    {"label": "Operating Revenue", "value": "operating_revenue"},
    {"label": "Other Income", "value": "other_revenue"},
    {"label": "Cost of Sales", "value": "cost_of_sales"},
    {"label": "Operating Expense", "value": "operating_expense"},
    {"label": "Other Expense", "value": "other_expense"},
    {"label": "Tax Expense", "value": "tax_expense"},
]

NORMAL_BALANCE_OPTIONS = [
    {"label": "Debit", "value": "debit"},
    {"label": "Credit", "value": "credit"},
]


ACCOUNT_FIELDS = {
    "company": field.lookup(
        tab="general",
        label="Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        default="$me.placement.company",
        required=True,
        table=True,
        filter={"group": "quick", "order": 10},
        search=False,
        sortable=True,
        overview=True,
        order=10,
        help_text=(
            "Bagan akun berdiri sendiri per badan usaha. Kode yang sama "
            "boleh dipakai dua perusahaan dengan arti berbeda."
        ),
    ),

    "code": field.text(
        tab="general",
        label="Account Code",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        order=20,
        help_text=(
            "Bebas — tidak ada format yang dipaksakan sistem. Panjang "
            "dan penomorannya mengikuti kebijakan perusahaan."
        ),
    ),

    "name": field.text(
        tab="general",
        label="Account Name",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        order=30,
    ),

    "parent": field.lookup(
        tab="general",
        label="Parent Account",
        lookup_endpoint="/api/finance/lookup/account-groups/",
        lookup_params={"company_id": "$company"},
        depends_on="company",
        display_key="parent_name",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        order=40,
        help_text=(
            "Hanya akun grup yang bisa jadi induk. Kosongkan untuk akun "
            "tingkat teratas."
        ),
    ),

    "account_type": field.select(
        tab="general",
        label="Account Type",
        options=ACCOUNT_TYPE_OPTIONS,
        display_key="account_type_label",
        required=True,
        table=True,
        filter={"group": "quick", "order": 20},
        sortable=True,
        overview=True,
        order=50,
        help_text=(
            "Menentukan saldo normal dan penempatannya di neraca atau "
            "laba rugi. Harus sama dengan induknya."
        ),
    ),

    "account_category": field.select(
        tab="general",
        label="Category",
        options=ACCOUNT_CATEGORY_OPTIONS,
        display_key="account_category_label",
        required=False,
        table=False,
        filter={"group": "advanced", "order": 10},
        sortable=False,
        order=60,
        help_text="Baris penyajian di laporan keuangan. Opsional.",
    ),

    "normal_balance": field.select(
        tab="general",
        label="Normal Balance",
        options=NORMAL_BALANCE_OPTIONS,
        required=False,
        table=False,
        filter=False,
        order=70,
        help_text=(
            "Kosongkan untuk mengikuti golongan akun. Diisi hanya untuk "
            "akun kontra — akumulasi penyusutan, potongan penjualan."
        ),
    ),

    "posting_allowed": field.switch(
        tab="general",
        label="Posting Allowed",
        default=True,
        table=True,
        filter={"group": "quick", "order": 30},
        sortable=False,
        overview=True,
        order=80,
        help_text=(
            "Mati = akun grup/judul yang tidak menerima jurnal. Akun "
            "yang punya anak selalu jadi grup."
        ),
    ),

    "control_account": field.switch(
        tab="behaviour",
        label="Control Account",
        default=False,
        table=False,
        filter=False,
        order=90,
        help_text=(
            "Saldonya dikendalikan buku pembantu (piutang, utang, aset "
            "tetap)."
        ),
    ),

    "reconciliation_required": field.switch(
        tab="behaviour",
        label="Reconciliation Required",
        default=False,
        table=False,
        filter=False,
        order=100,
        help_text="Mutasinya harus direkonsiliasi — kas, bank, kliring.",
    ),

    "default_currency": field.lookup(
        tab="behaviour",
        label="Currency Restriction",
        lookup_endpoint="/api/administration/currency/lookup/currencies/",
        display_key="default_currency_code",
        required=False,
        table=False,
        filter=False,
        order=110,
        help_text=(
            "Kosong = menerima mata uang apa pun. Diisi untuk rekening "
            "bank valas."
        ),
    ),

    "sort_order": field.integer(
        tab="behaviour",
        label="Sort Order",
        default=0,
        table=False,
        filter=False,
        order=120,
    ),

    "is_active": field.switch(
        tab="general",
        label="Active",
        default=True,
        table=True,
        filter={"group": "quick", "order": 40},
        sortable=False,
        order=130,
    ),

    "description": field.textarea(
        tab="behaviour",
        label="Notes",
        required=False,
        table=False,
        filter=False,
        order=140,
    ),
}


# Kolom turunan dari serializer.
#
# Tidak satu pun punya `tab`, dan itulah yang membuatnya tidak muncul di
# form: tab form mengumpulkan field lewat `tab=`-nya. Yang disetel di
# sini cuma perilakunya di tabel.
ACCOUNT_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "company_name",
        "parent_name",
        "account_type_label",
        "account_category_label",
        "default_currency_code",
        "is_group",
        "has_entries",
        "can_delete",
        "path",
        "level",
    )
}

# Satu-satunya kolom turunan yang memang ditampilkan: saldo normal yang
# **berlaku**. Kolom mentahnya boleh kosong (= ikut golongan), dan
# kolom kosong di layar terbaca seperti akun yang belum diatur.
ACCOUNT_DISPLAY_FIELDS["effective_normal_balance"] = field.text(
    label="Normal Balance",
    table=True,
    filter=False,
    search=False,
    sortable=False,
    order=85,
)


ACCOUNT_SCHEMA = {
    "module": "finance/chart-of-accounts",
    "name": "Account",
    "label": "Chart of Accounts",
    # Wajib eksplisit: `framework_module` memakai tanda hubung
    # (`chart-of-accounts`) sementara rutenya `accounts/`. Generator FE
    # menurunkan endpoint dari slug module kalau kunci ini kosong, dan
    # hasilnya URL yang tidak ada — tabelnya lalu menampilkan "No
    # results." tanpa satu pun pesan error.
    "endpoint": "/api/finance/accounts/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Chart of Accounts",
            description=(
                "Susunan perkiraan per perusahaan. Akun grup menampung, "
                "akun posting menerima jurnal."
            ),
            size="xl",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=False,
            export=True,
        ),
    },

    "tabs": [
        tabs.form("general", label="General"),
        tabs.form("behaviour", label="Behaviour"),
    ],

    "actions": [
        action.save(),
        action.save_and_close(),
        action.export(),
    ],

    "fields": {
        **ACCOUNT_FIELDS,
        **ACCOUNT_DISPLAY_FIELDS,
    },
}
