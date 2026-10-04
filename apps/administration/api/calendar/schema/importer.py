"""
Deklarasi fitur import Work Calendar dan Holiday.

`preview_columns` di sini harus sejajar dengan key yang dihasilkan
`build_preview_row()` masing-masing importer — kolom yang keynya tidak
ada di baris preview tampil **kosong tanpa satu pun pesan**, dan yang
memeriksanya menyimpulkan datanya yang tidak terbaca. Daftar yang sama
juga ada di `preview_columns` milik importer; keduanya wajib diubah
bersamaan, karena yang dibaca frontend yang ini dan yang dipakai
laporan error yang itu.
"""

from apps.framework.builders import importer


WORK_CALENDAR_IMPORT_SCHEMA = importer.config(
    module="administration/calendar/work-calendar",

    title="Import Work Calendars",

    description=(
        "Import pola hari kerja. Kolom scope menentukan siapa yang "
        "terkena: GLOBAL (kosongkan company dan location — satu baris "
        "berlaku untuk seluruh perusahaan, termasuk yang dibuat "
        "kemudian), COMPANY, atau LOCATION. Jangan membuat satu baris "
        "per perusahaan untuk pola yang sama; itu justru yang "
        "digantikan cakupan GLOBAL. Baris yang cakupan + company + "
        "location + kodenya sudah ada ditandai UPDATE di preview, "
        "bukan ditimpa diam-diam."
    ),

    completed_title="Work Calendar Import Completed",

    completed_description=(
        "Periksa kolom Applies To di daftar Work Calendar — baris "
        "GLOBAL harus berbunyi 'All Companies'. Kalender yang baru "
        "masuk langsung dipakai resolver untuk perhitungan cuti, "
        "absensi, dan prorata gaji."
    ),

    back_label="Back to Work Calendar",
    back_route="/administration/calendar",

    file_label="CSV File",

    preview_columns=[
        importer.column("row_number", "Row"),
        importer.column("code", "Code"),
        importer.column("name", "Name"),
        importer.column("scope", "Scope"),
        importer.column("applies_to", "Applies To"),
        importer.column("working_days", "Working Days"),
        importer.column("is_default", "Default"),
        importer.column("is_active", "Active"),
        importer.column("action", "Action"),
    ],
)


HOLIDAY_IMPORT_SCHEMA = importer.config(
    module="administration/calendar/holiday",

    title="Import Holidays",

    description=(
        "Import hari libur. Libur nasional cukup **satu baris** "
        "bercakupan GLOBAL (sinonim yang diterima: NATIONAL) dengan "
        "company dan location dikosongkan — jangan menulisnya ulang "
        "per perusahaan. Untuk sebagian perusahaan saja, pakai scope "
        "SELECTED_COMPANIES dan tulis kode perusahaannya dipisah koma "
        "di kolom company. Baris yang cakupan + tanggal + kodenya "
        "sudah ada ditandai UPDATE di preview."
    ),

    completed_title="Holiday Import Completed",

    completed_description=(
        "Periksa kolom Applies To di daftar Holiday — libur nasional "
        "harus muncul sebagai satu baris 'All Companies', bukan satu "
        "baris per perusahaan. Baris hasil import langsung berlaku; "
        "yang menunggu review hanya hasil sinkronisasi sumber luar."
    ),

    back_label="Back to Holiday",
    back_route="/administration/calendar",

    file_label="CSV File",

    preview_columns=[
        importer.column("row_number", "Row"),
        importer.column("date", "Date"),
        importer.column("code", "Code"),
        importer.column("name", "Name"),
        importer.column("scope", "Scope"),
        importer.column("applies_to", "Applies To"),
        importer.column("is_national", "National"),
        importer.column("is_recurring", "Recurring"),
        importer.column("action", "Action"),
    ],
)
