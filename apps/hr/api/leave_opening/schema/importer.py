from apps.framework.builders import importer


"""
Deklarasi fitur import Saldo Awal Cuti.

`preview_columns` harus sejajar dengan key yang dihasilkan
`LeaveOpeningBalanceImporter.build_preview_row()` — kolom yang keynya
tidak ada di baris preview tampil kosong tanpa satu pun pesan. Daftar
yang sama ada di `preview_columns` milik importer itu; keduanya wajib
diubah bersamaan, karena yang dibaca frontend yang ini dan yang dibaca
laporan error yang itu.
"""


LEAVE_OPENING_IMPORT_SCHEMA = importer.config(
    module="hr/leave-opening-balances",

    title="Import Leave Opening Balance",

    description=(
        "Import saldo cuti awal dari sistem lama — saldo aktual pegawai "
        "pada tanggal go-live. Satu baris per pegawai per jenis cuti; "
        "pegawai yang sudah punya saldo awal ditolak sebagai duplikat, "
        "bukan ditimpa. Kolom tanggal boleh dikosongkan — ikut tanggal "
        "Leave Go-Live perusahaannya. Saldo nol sah dan tetap perlu "
        "diimport; saldo di atas nol untuk pegawai yang belum berhak "
        "ditandai REVIEW, tidak ditolak dan tidak diubah."
    ),

    completed_title="Leave Opening Balance Import Completed",

    completed_description=(
        "Barisnya masuk sebagai DRAFT dan belum memengaruhi kartu cuti "
        "siapa pun. Periksa angkanya di daftar Leave Opening Balance — "
        "terutama baris berstatus REVIEW — lalu tekan Post agar jadi "
        "saldo pegawai."
    ),

    back_label="Back to Leave Opening Balance",
    back_route="/hr/leave-opening-balances",

    file_label="CSV File",

    preview_columns=[
        importer.column("row_number", "Row"),
        importer.column("employee_code", "Employee Code"),
        importer.column("employee_name", "Employee"),
        importer.column("leave_type", "Leave Type"),
        importer.column("join_date", "Join Date"),
        importer.column("eligible_date", "Eligible Date"),
        importer.column("opening_date", "Opening Date"),
        importer.column("days", "Opening Balance", align="right"),
        importer.column("validation", "Validation"),
        importer.column("remark", "Remark"),
        importer.column("reason", "Reason"),
    ],
)
