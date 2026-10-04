"""
Cakupan baris `PayrollRunEmployee` — satu tempat, dipakai bersama.

Gaji seseorang dijaga **dua lapis**, dan keduanya harus ikut ke mana pun
baris payroll dibaca:

* `DataScopeService` menjawab "baris milik organisasi mana", memakai
  kolom snapshot di baris itu sendiri — bukan `employee__organization__*`.
  Baris payroll yang sudah terkunci tidak boleh berpindah pemiliknya
  karena pegawainya dimutasi bulan depan.
* `EmployeeDataVisibility` menjawab "gaji **siapa** yang boleh dibaca
  akun ini", lewat `EmployeeDataPolicy` kelompok `FIELD_PAYROLL` — lapis
  yang sama yang menutup tab Payroll di kartu pegawai.

Kenapa modul tersendiri
-----------------------
Sebelumnya petanya ditulis di `PayrollRunEmployeeViewSet.data_scope`,
dan lapis keduanya ikut sendiri lewat `EmployeeDataSubjectMixin.
filter_queryset()`. Itu benar untuk endpoint daftar — dan **tidak ikut
sama sekali** untuk endpoint lain yang merakit querysetnya sendiri.

`/api/payroll/payroll-runs/<id>/summary/` adalah endpoint seperti itu.
Ia menjumlahkan `PayrollRunEmployee` langsung dari manager, jadi tidak
satu pun dari dua lapis di atas pernah dilewati: akun yang membuka
`/api/payroll/payroll-run-employees/?run=8` dan mendapat **nol baris**
tetap membaca total Rp 132.378.341 di `summary/`. Angkanya bocor lewat
pintu yang tidak dijaga siapa pun, dan diamnya sempurna — tidak ada
error, tidak ada baris, cuma jumlah yang seharusnya tidak pernah ia
lihat.

Bentuk `filter_queryset()` tidak bisa menutup itu: ia hanya menyaring
queryset yang **dikembalikan** viewset, sementara action seperti
`summary` membangun agregatnya sendiri. Karena itu penjagaannya
dipindah ke fungsi yang bisa dipanggil dari mana saja, dan viewset-nya
ikut memakai peta yang sama supaya tidak ada dua definisi yang harus
tetap sepakat.

Catatan untuk yang menambah pembaca baru
----------------------------------------
Tiap pembaca baru baris payroll di luar `filter_queryset()` memanggil
`scope_run_employees()` — bukan menyalin petanya. Yang sudah memakainya:
`PayrollRunEmployeeViewSet.data_scope`, rekap
`payroll-runs/<id>/summary/`, dan `PayrollDashboardService.lines()`
(satu-satunya pintu ke angka payroll seluruh dashboard). Peta di bawah
karena itu boleh bergeser di satu tempat saja.
"""

from __future__ import annotations

from apps.accounts.permissions import view_permission_for
from apps.accounts.scoping import DataScopeService
from apps.administration.models import EmployeeDataSubject
from apps.hr.api.employee.visibility import EmployeeDataVisibility


# Peta `{jenis cakupan: jalur ORM}` untuk `PayrollRun` — dokumennya,
# bukan barisnya.
#
# Tinggal di sini, bukan di `PayrollRunViewSet.data_scope`, sejak
# Finalize ikut dijaga cakupan di lapisan service (PF-0D): viewset dan
# service harus menyaring lewat peta yang **sama**, dan dua salinan
# aturan cakupan cepat atau lambat berbeda — yang satu akan membuka apa
# yang ditutup satunya.
PAYROLL_RUN_SCOPE = {
    "company": "company",
    "branch": "branch",
    "location": "location",
    "department": "department",
    "section": "section",
}


# Peta `{jenis cakupan: jalur ORM}` untuk `PayrollRunEmployee`.
#
# Menyaring lewat kolom snapshot milik barisnya sendiri
# (`company`, `department`, …), **bukan** lewat penempatan pegawainya
# hari ini: baris payroll yang sudah terkunci tidak boleh berpindah
# pemiliknya karena orangnya dimutasi bulan depan.
PAYROLL_RUN_EMPLOYEE_SCOPE = {
    "company": "company",
    "branch": "branch",
    "location": "location",
    "division": "division",
    "department": "department",
    "section": "section",
    "own": "employee__user_id",
}


def scope_run_employees(queryset, user):
    """
    Menerapkan **dua** lapis cakupan pada queryset `PayrollRunEmployee`.

    Dipanggil endpoint mana pun yang membaca baris payroll di luar
    jalur `filter_queryset()` viewset — termasuk yang cuma
    menjumlahkannya dan tidak pernah mengirim satu baris pun. Agregat
    bocor persis sama seperti baris bocor; yang membedakan cuma
    apakah kebocorannya terlihat.

    `user` tanpa autentikasi ditutup, bukan dibuka: itu semantik
    `EmployeeDataVisibility.visible_employees_q`, dan endpoint payroll
    seluruhnya `IsAuthenticated` jadi keadaan itu memang tidak muncul
    di jalur normal.

    Cakupannya dihitung **per izin** (Stage 3B). Tanpa
    `required_permission`, cakupan seluruh role pemegang akun dipakai
    untuk membaca baris payroll — jadi role yang tidak memberi izin
    payroll pun ikut melebarkannya. Itu persis yang membuat pemegang
    cakupan luas tanpa izin payroll tetap membaca total di dashboard
    sementara daftarnya nol: dua pintu ke angka yang sama, dijaga dua
    aturan yang berbeda.
    """
    queryset = DataScopeService.filter(
        queryset,
        PAYROLL_RUN_EMPLOYEE_SCOPE,
        user,
        required_permission=view_permission_for(queryset.model),
    )

    allowed = EmployeeDataVisibility.visible_employees_q(
        subject=str(EmployeeDataSubject.FIELD_PAYROLL),
        user=user,
    )

    if allowed is None:
        return queryset

    from apps.hr.models import Employee

    return queryset.filter(employee__in=Employee.objects.filter(allowed))


def payable_run_employees(*, run, user):
    """
    Baris yang **dibayar** pada satu run dan boleh dibaca `user`.

    Yang dikecualikan dari run tidak ikut: barisnya sengaja tetap ada
    di dokumen supaya "kenapa si A tidak dibayar" punya jawaban, tapi
    ia bukan bagian dari angka yang dibayarkan — aturan yang sama
    dengan `PayrollRunService._refresh_totals`, jadi pemegang akses
    penuh membaca angka yang identik dengan kolom total yang dibekukan
    di run.
    """
    from apps.payroll.models import PayrollRunEmployee

    return scope_run_employees(
        PayrollRunEmployee.objects.filter(
            run=run,
            is_deleted=False,
            is_excluded=False,
        ),
        user,
    )


def visible_findings(*, summary: dict | None, visible_employee_ids) -> dict:
    """
    `validation_summary` yang sudah dibuang temuan orang luar cakupan.

    Ringkasan itu dibekukan atas **seluruh** run dan tidak tahu siapa
    yang membacanya, sementara tiap temuan membawa nama dan nomor
    pegawai di pesannya. Mengirimnya apa adanya membocorkan daftar
    orang yang barisnya sendiri sudah disembunyikan — dan `counts`-nya
    membocorkan berapa banyak.

    Temuan tingkat run (yang tidak menyebut pegawai) tetap tampil untuk
    semua: "kebijakan prorata belum dipilih" adalah keadaan dokumennya,
    bukan gaji seseorang.

    `counts` dihitung ulang dari yang tersisa. Menyalinnya apa adanya
    berarti angka di sana menjawab pertanyaan yang berbeda dari daftar
    di sebelahnya — dan yang lebih besar dari keduanya justru yang
    tidak boleh terbaca.
    """
    summary = summary or {}

    if not summary:
        return {}

    visible = set(visible_employee_ids)

    def keep(items):
        return [
            item
            for item in items or []
            if not item.get("employee") or item.get("employee") in visible
        ]

    errors = keep(summary.get("errors"))
    warnings = keep(summary.get("warnings"))

    counts = dict(summary.get("counts") or {})

    counts.update(
        {
            "errors": len(errors),
            "warnings": len(warnings),
        },
    )

    # Cacah pegawai ikut disesuaikan kalau memang ada di ringkasannya:
    # "15 pegawai" di sebelah nol baris adalah bocoran yang sama,
    # cuma berbentuk satu angka.
    if "employees" in counts:
        counts["employees"] = len(visible)

    if "excluded" in counts:
        counts.pop("excluded")

    return {"errors": errors, "warnings": warnings, "counts": counts}
