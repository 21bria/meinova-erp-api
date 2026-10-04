from apps.administration.models import NumberingSequence

from .base import seed_reference


NUMBERINGS = [
    # HR
    ("hr", "employee", "EMP", "Employee", "EMP", "", "-", 5, True, False),
    ("hr", "leave", "LV", "Leave Request", "LV", "", "-", 5, True, False),
    # Jadwal roster. Nomornya tetap berawalan RST, bukan TR — TR
    # dipakai dokumen pengajuan kepulangan, dan dua dokumen berbeda
    # tidak boleh berbagi deret nomor yang sama.
    ("hr", "site_rotation", "RST", "Roster Schedule", "RST", "", "-", 5, True, False),
    ("hr", "travel_request", "TR", "Travel Request", "TR", "", "-", 5, True, False),
    # Perjalanan dinas pegawai. Deret sendiri: BT bukan TR (kepulangan
    # site) dan bukan VR (kunjungan tamu) — tiga dokumen berbeda tidak
    # berbagi satu deret. Reset tahunan: BT-2026-00001.
    ("hr", "business_trip", "BT", "Business Trip", "BT", "", "-", 5, True, False),
    # Dokumen perubahan kepegawaian (kontrak, jenis, penempatan, gaji).
    # Deret sendiri: nomornya dirujuk di SK dan surat, dan dua jenis
    # dokumen yang berbeda tidak boleh berbagi satu deret.
    ("hr", "employee_action", "EAC", "Employee Action", "EAC", "", "-", 5, True, False),
    # Setup roster massal dan penyesuaiannya. Dua deret, bukan satu:
    # yang pertama dokumen perencanaan yang terbit sekali per site,
    # yang kedua dokumen operasional yang terbit tiap kali kapal
    # bergeser. Menyatukannya membuat nomor RSU melompat-lompat tanpa
    # ada yang bisa menjelaskan kenapa.
    ("hr", "roster_setup", "RSU", "Roster Setup", "RSU", "", "-", 5, True, False),
    ("hr", "roster_adjustment", "RAJ", "Roster Adjustment", "RAJ", "", "-", 5, True, False),

    # Visitor Management. Nomor tamu **tidak** reset tahunan: ia
    # identitas satu orang di master, bukan nomor dokumen — vendor yang
    # terdaftar 2026 tetap VIS-000042 di 2027, dan menyetelnya reset
    # akan menerbitkan nomor yang sama untuk orang yang berbeda.
    # Dokumen kunjungan dan kartunya tetap reset seperti dokumen lain.
    ("hr", "external_visitor", "VIS", "External Visitor", "VIS", "", "-", 6, False, False),
    ("hr", "visitor_request", "VR", "Visitor Request", "VR", "", "-", 6, True, False),
    ("hr", "visitor_pass", "VP", "Visitor Pass", "VP", "", "-", 6, True, False),

    # Izin kehadiran. Deret sendiri, bukan menumpang deret cuti:
    # nomornya dirujuk di baris presensi yang dibebaskan, dan dua
    # jenis dokumen yang berbeda tidak boleh berbagi satu deret.
    (
        "hr", "attendance_permission", "APRM",
        "Attendance Permission", "APRM", "", "-", 6, True, False,
    ),

    # Payroll. Slip punya deretnya sendiri: nomor slip tercetak di
    # dokumen yang dipegang pegawai, dan berbagi deret dengan nomor run
    # membuat nomornya melompat tanpa ada yang bisa menjelaskan kenapa.
    #
    # **Kodenya `PRUN`, bukan `PAY`.** `seed_reference` mencocokkan baris
    # lewat `code` saja, sementara kunci unik tabelnya
    # (company, module, document_type) — jadi dua baris ber-`code` sama
    # saling menimpa, dan yang terbaca terakhir yang menang. Waktu baris
    # ini masih `PAY` ia ditimpa `finance/payment` di bawah, dan
    # akibatnya deret payroll **tidak pernah ketemu**: dokumennya terbit
    # tanpa nomor, diam-diam. Prefix cetaknya tetap `PAY`, jadi nomor
    # yang muncul tetap PAY-2026-00001.
    ("payroll", "payroll_run", "PRUN", "Payroll Run", "PAY", "", "-", 5, True, False),
    ("payroll", "payslip", "SLP", "Payslip", "SLP", "", "-", 6, True, False),

    # Procurement
    ("procurement", "purchase_request", "PR", "Purchase Request", "PR", "", "-", 5, True, False),
    ("procurement", "purchase_order", "PO", "Purchase Order", "PO", "", "-", 5, True, False),

    # Inventory
    ("inventory", "goods_receipt", "GR", "Goods Receipt", "GR", "", "-", 5, True, False),
    ("inventory", "goods_issue", "GI", "Goods Issue", "GI", "", "-", 5, True, False),

    # Finance
    ("finance", "journal", "JV", "Journal Voucher", "JV", "", "-", 5, False, True),
    ("finance", "payment", "PAY", "Payment", "PAY", "", "-", 5, False, True),

    # Sales
    ("sales", "quotation", "SQ", "Sales Quotation", "SQ", "", "-", 5, True, False),
    ("sales", "sales_order", "SO", "Sales Order", "SO", "", "-", 5, True, False),
    ("sales", "invoice", "INV", "Invoice", "INV", "", "-", 5, True, False),

    # Asset Management. Nomor aset adalah **identitas** unit fisik, bukan
    # nomor dokumen — jadi tidak reset tahunan (pola `external_visitor`):
    # laptop yang terdaftar 2026 tetap AST-000042 di 2027.
    ("assets", "asset", "AST", "Asset", "AST", "", "-", 6, False, False),
    # Dokumen pergerakan aset — nomor dokumen biasa, reset tahunan.
    ("assets", "asset_assignment", "AAS", "Asset Assignment", "AAS", "", "-", 5, True, False),
    ("assets", "asset_return", "ART", "Asset Return", "ART", "", "-", 5, True, False),
    ("assets", "asset_transfer", "ATR", "Asset Transfer", "ATR", "", "-", 5, True, False),
]


def seed_numbering() -> None:
    seed_reference(
        NumberingSequence,
        [
            {
                "company": None,
                "module": module,
                "document_type": document_type,
                "code": code,
                "name": name,
                "prefix": prefix,
                "suffix": suffix,
                "separator": separator,
                "padding": padding,
                "current_number": 0,
                "reset_yearly": reset_yearly,
                "reset_monthly": reset_monthly,
            }
            for (
                module,
                document_type,
                code,
                name,
                prefix,
                suffix,
                separator,
                padding,
                reset_yearly,
                reset_monthly,
            ) in NUMBERINGS
        ],
    )