"""
Schema UI komponen tunjangan.

Basis menentukan kolom mana yang berarti, dan itu diberitahukan lewat
`visible_when` supaya form tidak menampilkan Rate pada komponen yang
nilainya tetap — kolom yang tidak berarti tapi tetap terlihat adalah
undangan untuk mengisinya.
"""

from apps.framework.builders import field, ui


# Label-nya **sama persis** dengan label enum `PayrollBasis`, dan itu
# disengaja: kolom tabel membacanya lewat `basis_label` yang berasal
# dari enum, jadi menulis kalimat yang berbeda di sini akan membuat
# satu komponen tampil "Nominal x hari hadir" di formulir dan "Amount x
# Attendance Day" di tabel — dua nama untuk satu hal, di satu layar.
ALLOWANCE_BASIS_OPTIONS = [
    {"label": "Fixed Amount", "value": "fixed"},
    {"label": "% of Basic Salary", "value": "percent_of_basic"},
    {"label": "Amount x Working Day", "value": "per_working_day"},
    {"label": "Amount x Paid Day", "value": "per_paid_day"},
    {"label": "Amount x Attendance Day", "value": "per_attendance_day"},
    {"label": "Amount x Overtime Hour", "value": "per_overtime_hour"},
]

PERCENT_BASES = ["percent_of_basic"]

AMOUNT_BASES = [
    "fixed",
    "per_working_day",
    "per_paid_day",
    "per_attendance_day",
    "per_overtime_hour",
]


ALLOWANCE_TEMPLATE_LINE_SCHEMA = {
    "module": "payroll/allowance-template-lines",
    "name": "AllowanceTemplateLine",
    "label": "Allowance Component",
    "endpoint": "/api/payroll/allowance-template-lines/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Allowance Components",
            description=(
                "Komponen di dalam Allowance Template. Template-nya "
                "sendiri tetap dikelola di layar Allowance Templates."
            ),
            size="xl",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            export=True,
        ),
    },

    "fields": {
        "template": field.lookup(
            label="Allowance Template",
            lookup_endpoint="/api/payroll/allowance-templates/lookup/",
            display_key="template_name",
            required=True,
            table=True,
            filter=True,
            search=True,
            sortable=True,
            order=10,
        ),
        "code": field.text(
            label="Component Code",
            placeholder="e.g. TRANSPORT",
            required=True,
            table=True,
            search=True,
            sortable=True,
            order=20,
        ),
        "name": field.text(
            label="Component Name",
            placeholder="e.g. Tunjangan Transport",
            required=True,
            table=True,
            search=True,
            sortable=True,
            order=30,
        ),
        "sequence": field.integer(
            label="Sequence",
            default=1,
            table=True,
            sortable=True,
            order=40,
        ),
        "basis": field.select(
            label="Calculation Basis",
            options=ALLOWANCE_BASIS_OPTIONS,
            default="fixed",
            required=True,
            table=True,
            filter=True,
            display_key="basis_label",
            order=50,
            help_text=(
                "Menentukan kolom mana yang dipakai: Amount untuk nilai "
                "tetap dan satuan, Rate untuk persentase. Working Day = "
                "hari berhak menurut kebijakan prorata perusahaan; "
                "Paid Day = hari berhak dikurangi alpa dan cuti tidak "
                "dibayar; Attendance Day = hari yang benar-benar hadir "
                "menurut absensi. Basis per hari sudah mengandung "
                "harinya, jadi nilainya tidak diprorata lagi."
            ),
        ),
        "amount": field.currency(
            label="Amount",
            min=0,
            table=True,
            sortable=True,
            visible_when={"basis": AMOUNT_BASES},
            order=60,
        ),
        "rate": field.decimal(
            label="Rate (%)",
            min=0,
            decimal_places=4,
            visible_when={"basis": PERCENT_BASES},
            table=False,
            order=70,
        ),
        "minimum_amount": field.currency(
            label="Minimum Amount",
            min=0,
            table=False,
            order=80,
            help_text=(
                "Dikenakan **sesudah** prorata, jadi artinya \"paling "
                "sedikit segini yang dibayar bulan ini\"."
            ),
        ),
        "maximum_amount": field.currency(
            label="Maximum Amount",
            min=0,
            table=False,
            order=90,
            help_text=(
                "Dikenakan **sesudah** prorata, jadi artinya \"paling "
                "banyak segini yang dibayar bulan ini\"."
            ),
        ),
        "is_taxable": field.boolean(
            label="Taxable",
            default=True,
            table=True,
            filter=True,
            # Kolomnya membaca label, bukan boolean-nya: generator
            # memetakan boolean ke Active/Inactive, dan "Active" tidak
            # menjawab apakah tunjangan ini menambah dasar pajak.
            display_key="is_taxable_label",
            order=100,
            help_text=(
                "Ikut menambah dasar perhitungan PPh21. Yang menentukan "
                "kebijakan perusahaan, bukan nama komponennya."
            ),
        ),
        "is_prorated": field.boolean(
            label="Prorated",
            default=True,
            table=True,
            display_key="is_prorated_label",
            # Saklar ini **hanya** berarti untuk basis bernilai bulanan
            # (Fixed dan % of Basic). Idealnya ia disembunyikan pada
            # basis per hari lewat `visible_when` — tapi dialek pendek
            # `{field: value}` yang dipakai seluruh codebase ini tidak
            # dikenali `MFormBuilder.evaluateRule`, yang menunggu
            # `{field, op, value}`; seluruh 193 aturan `visible_when`
            # di proyek ini karena itu tidak berpengaruh apa pun.
            # Memperbaikinya berarti menyalakan ke-193 aturan itu
            # sekaligus di semua module — di luar cakupan keputusan #3
            # dan dicatat sebagai utang framework.
            #
            # Yang bisa dilakukan sekarang: mengatakannya. Hint di
            # bawah menyebut syaratnya, kolom tabel menulis "Per hari
            # (tanpa prorata)", dan komponen hasilnya membawa
            # keterangan "tanpa prorata (basis sudah per hari nyata)".
            order=110,
            help_text=(
                "Hanya berlaku untuk basis Fixed Amount dan % of Basic "
                "Salary. Pegawai yang masuk atau berhenti di tengah "
                "periode menerima sebagian, mengikuti metode prorata "
                "gaji pokok perusahaan. Basis per hari mengabaikan "
                "saklar ini karena nilainya sudah mengandung harinya. "
                "Tidak dipengaruhi absen atau cuti tidak dibayar — itu "
                "jalur potongan yang terpisah."
            ),
        ),
        "description": field.textarea(
            label="Description",
            rows=3,
            layout="full",
            table=False,
            order=120,
        ),
        "is_active": field.boolean(
            label="Active",
            default=True,
            table=True,
            filter=True,
            order=999,
        ),
    },
}
