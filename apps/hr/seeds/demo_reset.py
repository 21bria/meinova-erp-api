"""
Membuang seluruh data uji sebelum dibangun ulang.

Dibutuhkan karena seed lain memakai `update_or_create` — aman diulang,
tapi **tidak pernah membuang** baris yang hilang dari daftarnya. Begitu
susunan peran data uji berubah (pegawai berganti jabatan, meja alur
bertambah), sisa susunan lama tetap tinggal: dokumen yang berjalan di
alur versi lama, pegawai yang role-nya sudah tidak dipakai, dan akun
yang masih memegang meja yang seharusnya sudah pindah orang.

Yang dibuang **hanya yang berawalan data uji** — nomor pegawai `HO`/
`SGA`/`LOK` dan dokumen miliknya. Master organisasi, master referensi, dan
definisi alur tidak disentuh: itu bukan data uji, dan membuangnya
berarti seed berikutnya memulai dari tenant kosong.

Hard delete, bukan soft: baris bertanda terhapus tetap menempati kunci
uniknya (`employee_number`, `uniq_workflow_open_instance`), jadi
membangun ulang justru gagal karena bentrok dengan bangkai sebelumnya.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction


# Awalan nomor pegawai data uji. Sengaja berbeda dari pola klien
# (`KW`, `IP`, `KPB`, …) supaya perintah ini tidak akan pernah
# menyentuh data sungguhan walau dijalankan di tenant yang salah.
# `LOK` menyusul begitu tenaga lokal site ikut diseed
# (`seed_demo_employees`). Awalan yang tertinggal di sini gagal dengan
# cara yang paling menyesatkan: reset melaporkan berhasil, lalu seed
# berikutnya ditolak `uniq_active_employee_number` oleh baris yang tidak
# pernah disebut siapa pun.
EMPLOYEE_PREFIXES = ["HO", "SGA", "LOK"]

# `BOD` sengaja **tidak** ikut, dan itu bukan kelalaian: dua pegawai
# direksi adalah bagian tetap tenant peragaan — merekalah yang
# membuktikan Feature Applicability (Employee Group `BOARD` mematikan
# seluruh proses operasional), dan membangunnya ulang tiap reset
# berarti kehilangan akun beserta perannya. Kalau suatu hari mereka
# memang harus ikut dibangun ulang, tambahkan prefix-nya di sini —
# bukan di pemanggil.
#
# `TRL` juga tidak ikut: itu lini uji teknis dengan manifestnya
# sendiri, bukan data peragaan manajemen.

# Akun data uji. Dicocokkan dengan awalan, bukan daftar tetap: nama
# akunnya ikut berubah tiap susunan perannya disusun ulang.
USERNAME_PREFIX = "demo."


def _employees():
    from django.db.models import Q

    from apps.hr.models import Employee

    condition = Q()

    for prefix in EMPLOYEE_PREFIXES:
        condition |= Q(employee_number__startswith=prefix)

    return Employee.objects.filter(condition)


@transaction.atomic
def run(*, log=print, keep_accounts: bool = False) -> dict:
    from apps.administration.models import Notification
    from apps.hr.models import (
        AttendanceLog,
        AttendanceLogVerification,
        AttendancePermission,
        EmployeeAction,
        EmployeeAttendance,
        EmployeeShiftAssignment,
        EmployeeEducation,
        EmployeeLeave,
        EmployeeOvertime,
        JobVacancy,
        LeaveBalance,
        LeaveOpeningBalance,
        RosterAdjustment,
        RosterSetupLine,
        RosterSetupRequest,
        RotationCreditBalance,
        RotationCreditTransaction,
        RotationPeriod,
        SiteRotation,
        TrainingParticipant,
        TrainingProgram,
        TravelRequest,
        VisitorPass,
        VisitorRequest,
    )
    from apps.hr.seeds.demo_hr_records import TRAINING_PREFIX, VACANCY_PREFIX
    from apps.workflow.models import WorkflowApproval, WorkflowInstance

    User = get_user_model()

    employees = _employees()

    employee_ids = list(employees.values_list("id", flat=True))
    user_ids = [
        pk for pk in employees.values_list("user_id", flat=True) if pk
    ]

    from django.db.models import Q

    counts: dict[str, int] = {}

    def drop(label, queryset):
        removed = queryset.count()

        queryset.delete()

        counts[label] = removed

        if removed:
            log(f"    {label:24} {removed}")

    log("  Membuang data uji:")

    # ------------------------------------------------------------------
    # Dokumen dulu, baru pegawainya
    # ------------------------------------------------------------------
    #
    # Urutannya penting: `WorkflowInstance` menunjuk dokumennya lewat
    # `object_id` bertipe string, jadi tidak ada cascade yang menolong —
    # menghapus dokumennya lebih dulu meninggalkan pengajuan yang
    # menunjuk baris yang sudah tidak ada, dan layar monitoring
    # menampilkannya sebagai dokumen tanpa judul.

    # Kunjungan tamu ditunjuk lewat **tiga** kolom pegawai — pemohon,
    # tuan rumah, dan (untuk tamu internal) tamunya sendiri — dan
    # ketiganya `PROTECT`. Menyaring lewat satu kolom saja meninggalkan
    # baris yang menahan pegawainya di langkah terakhir, dengan
    # `ProtectedError` yang tidak menyebut Visitor Request sama sekali.
    visitor_requests = VisitorRequest.objects.filter(
        Q(requester_id__in=employee_ids)
        | Q(host_employee_id__in=employee_ids)
        | Q(employee_id__in=employee_ids),
    )

    documents = list(
        TravelRequest.objects
        .filter(employee_id__in=employee_ids)
        .values_list("id", flat=True)
    ) + list(
        EmployeeLeave.objects
        .filter(employee_id__in=employee_ids)
        .values_list("id", flat=True)
    ) + list(
        visitor_requests.values_list("id", flat=True)
    )

    # Dua jalur, dan yang kedua yang menyelamatkan: dokumen ditunjuk
    # `object_id` bertipe string tanpa integritas referensial, jadi
    # pembersihan sebelumnya bisa meninggalkan pengajuan yang menunjuk
    # baris yang sudah tidak ada. Yang tersisa itu tetap memegang
    # `subject_employee` lewat FK ber-`PROTECT`, dan menghalangi
    # pegawainya dihapus dengan pesan yang tidak menyebut sebabnya.
    instances = WorkflowInstance.objects.filter(
        Q(module="hr", object_id__in=[str(pk) for pk in documents])
        | Q(subject_employee_id__in=employee_ids)
        | Q(submitted_by_id__in=user_ids),
    )

    drop(
        "keputusan approval",
        WorkflowApproval.objects.filter(instance__in=instances),
    )
    drop("pengajuan workflow", instances)

    # Kartu dulu, baru dokumennya: FK-nya CASCADE, tapi menghitungnya
    # terpisah membuat keluaran reset menyebut berapa kartu yang ikut
    # terbuang — angka yang tidak terbaca kalau ia hilang diam-diam
    # lewat cascade.
    drop(
        "kartu tamu",
        VisitorPass.objects.filter(request__in=visitor_requests),
    )
    drop("kunjungan tamu", visitor_requests)

    drop(
        "travel request",
        TravelRequest.objects.filter(employee_id__in=employee_ids),
    )
    drop(
        "catatan cuti",
        EmployeeLeave.objects.filter(employee_id__in=employee_ids),
    )
    # Dokumen perubahan kepegawaian menunjuk pegawainya lewat FK
    # ber-PROTECT, jadi yang tertinggal menghalangi pembuangan
    # pegawainya di langkah terakhir — dan kegagalannya menyebut
    # ProtectedError, bukan "masih ada Employee Action".
    drop(
        "employee action",
        EmployeeAction.objects.filter(employee_id__in=employee_ids),
    )
    # Dokumen saldo awal dulu, baru kartunya. FK-nya CASCADE lewat
    # `employee`, jadi barisnya memang ikut terbuang di langkah
    # terakhir — tapi diam-diam, tanpa pernah masuk hitungan reset. Yang
    # lebih merugikan: jalur reset yang **tidak** membuang pegawainya
    # meninggalkan dokumen ini utuh, dan import berikutnya ditolak
    # sebagai duplikat oleh baris yang tidak disebut laporan mana pun.
    drop(
        "saldo awal cuti",
        LeaveOpeningBalance.objects.filter(employee_id__in=employee_ids),
    )
    drop(
        "saldo cuti",
        LeaveBalance.objects.filter(employee_id__in=employee_ids),
    )
    # Izin kehadiran menunjuk pegawainya lewat FK ber-**PROTECT** dan
    # sebelumnya tidak pernah disebut di sini. Selama tabelnya kosong
    # kelalaian itu tak terlihat; begitu ada satu dokumen izin, reset
    # gagal di langkah terakhir dengan `ProtectedError` yang menyebut
    # nama tabel dan bukan nama modulnya.
    drop(
        "izin kehadiran",
        AttendancePermission.objects.filter(employee_id__in=employee_ids),
    )

    # Tap mentah dibuang **sebelum** baris presensinya: `AttendanceLog`
    # menunjuk dua-duanya (pegawai ber-PROTECT, presensi ber-SET_NULL),
    # dan urutan terbalik menyisakan tap yang menggantung tanpa hari
    # kerjanya.
    # Bukti verifikasi tap Self Service menunjuk log-nya dengan PROTECT dan
    # menolak `delete()` biasa — dibuang lewat jalur pembongkaran yang
    # dijaga, dengan cakupan yang sama, sebelum tap-nya.
    evidence = AttendanceLogVerification.objects.filter(
        log__employee_id__in=employee_ids,
    )
    removed = evidence.count()
    evidence.purge_for_governed_reset()
    counts["verifikasi tap"] = removed
    if removed:
        log(f"    {'verifikasi tap':24} {removed}")

    drop(
        "tap mesin",
        AttendanceLog.objects.filter(employee_id__in=employee_ids),
    )

    drop(
        "absensi",
        EmployeeAttendance.objects.filter(employee_id__in=employee_ids),
    )

    # Penugasan shift ikut dibuang. Kalau tidak, pembangunan ulang
    # menabrak pemeriksaan tumpang tindih milik `clean()` — baris lama
    # masih menempati rentang yang sama, dan seed berhenti dengan pesan
    # yang menunjuk tanggal alih-alih menyebut data uji lama.
    drop(
        "penugasan shift",
        EmployeeShiftAssignment.objects.filter(
            employee_id__in=employee_ids,
        ),
    )

    # Ledger dulu: `RotationCreditTransaction` menunjuk rencana dan
    # penyesuaian, dan `soft_delete()`-nya sengaja melempar — ledger
    # append-only. Di sini hard delete, karena yang dibuang memang data
    # uji dan bukan koreksi pembukuan.
    drop(
        "kredit rotasi",
        RotationCreditTransaction.objects.filter(
            employee_id__in=employee_ids,
        ),
    )
    drop(
        "saldo kredit",
        RotationCreditBalance.objects.filter(employee_id__in=employee_ids),
    )
    drop(
        "penyesuaian roster",
        RosterAdjustment.objects.filter(employee_id__in=employee_ids),
    )

    # Periode dibuang eksplisit walau `SiteRotation` meng-cascade:
    # `RotationPeriod.employee_leave` menunjuk catatan cuti yang baru
    # saja hilang, dan urutan yang salah menyisakan baris menggantung.
    drop(
        "periode roster",
        RotationPeriod.objects.filter(rotation__employee_id__in=employee_ids),
    )
    drop(
        "dokumen roster",
        SiteRotation.objects.filter(employee_id__in=employee_ids),
    )

    # Dokumen setup ikut, kalau tidak setiap pembangunan ulang
    # meninggalkan satu RSU tanpa baris — terbaca seperti dokumen yang
    # gagal disimpan, padahal barisnya ikut terbuang bersama pegawainya.
    # Baris dulu, baru kepalanya — tapi id kepalanya dicatat lebih dulu:
    # sesudah barisnya hilang, tidak ada lagi yang menghubungkan dokumen
    # itu ke pegawai data uji, dan "dokumen tanpa baris" sebagai penanda
    # akan ikut membuang dokumen kosong buatan pengguna.
    setup_ids = list(
        RosterSetupLine.objects
        .filter(employee_id__in=employee_ids)
        .values_list("request_id", flat=True)
        .distinct()
    )

    drop(
        "baris setup roster",
        RosterSetupLine.objects.filter(employee_id__in=employee_ids),
    )
    drop(
        "dokumen setup roster",
        RosterSetupRequest.objects.filter(pk__in=setup_ids),
    )

    # Peserta pelatihan menunjuk pegawainya lewat FK ber-**PROTECT**,
    # jadi yang tertinggal menggagalkan pembuangan pegawai di langkah
    # terakhir — dan kegagalannya berbunyi `ProtectedError`, bukan
    # "masih ada peserta pelatihan". Programnya sendiri dibuang lewat
    # awalan kodenya: program pelatihan bukan milik satu pegawai, jadi
    # yang buatan seed harus bisa dibedakan dari yang diketik orang.
    drop(
        "peserta pelatihan",
        TrainingParticipant.objects.filter(employee_id__in=employee_ids),
    )
    drop(
        "program pelatihan",
        TrainingProgram.objects.filter(code__startswith=TRAINING_PREFIX),
    )
    drop(
        "lowongan",
        JobVacancy.objects.filter(code__startswith=VACANCY_PREFIX),
    )
    drop(
        "lembur",
        EmployeeOvertime.objects.filter(employee_id__in=employee_ids),
    )
    drop(
        "riwayat pendidikan",
        EmployeeEducation.objects.filter(employee_id__in=employee_ids),
    )

    # ------------------------------------------------------------------
    # Payroll: barisnya, bukan runnya
    # ------------------------------------------------------------------
    #
    # `PayrollRunEmployee`, `Payslip`, dan `PayrollInput` memegang
    # pegawainya lewat FK ber-**PROTECT**. Selama ini tidak satu pun
    # disebut di sini, jadi reset di tenant yang sudah pernah
    # menjalankan payroll **selalu** gagal di langkah terakhir — dan
    # pesannya menyebut `payroll_run_employee`, tabel yang tidak pernah
    # muncul di perintah ini.
    #
    # Yang dibuang **hanya barisnya**. Kepala run dan periodenya
    # dibiarkan: keduanya dokumen milik HR, bukan data uji, dan run
    # kosong yang tertinggal jauh lebih mudah dijelaskan daripada
    # periode yang hilang beserta penomorannya.
    from apps.payroll.models import (
        PayrollInput,
        PayrollRun,
        PayrollRunEmployee,
        Payslip,
    )

    # Run yang sudah dikunci membawa kejadian akuntansi dan jurnal di
    # modul Finance yang tidak dilihat perintah ini sama sekali.
    # Membuang barisnya diam-diam meninggalkan jurnal yang menunjuk
    # perhitungan yang tidak ada lagi — dan itu tidak bisa diperbaiki
    # dari sisi HR.
    locked = list(
        PayrollRun.objects
        .filter(
            is_deleted=False,
            status="finalized",
            employees__employee_id__in=employee_ids,
        )
        .values_list("document_number", flat=True)
        .distinct()
    )

    if locked:
        raise RuntimeError(
            "Ada payroll run yang sudah FINALIZED memakai pegawai data "
            f"uji ({', '.join(locked)}). Run terkunci membawa kejadian "
            "akuntansi; batalkan atau koreksi runnya lewat modul "
            "Payroll dulu, jangan dibuang dari sini.",
        )

    drop(
        "payroll input",
        PayrollInput.objects.filter(employee_id__in=employee_ids),
    )
    drop(
        "slip gaji",
        Payslip.objects.filter(employee_id__in=employee_ids),
    )
    drop(
        "baris run payroll",
        PayrollRunEmployee.objects.filter(employee_id__in=employee_ids),
    )

    drop(
        "notifikasi",
        Notification.objects.filter(user_id__in=user_ids),
    )

    drop("pegawai", _employees())

    if keep_accounts:
        log("    (akun dipertahankan)")
    else:
        # Akun ikut dibuang supaya role yang menempel padanya tidak
        # tertinggal. Akun yang masih memegang `KTT` sesudah
        # perannya pindah orang membuat satu meja punya dua approver,
        # dan itu tidak terlihat sampai dokumennya diajukan.
        drop(
            "akun data uji",
            User.objects.filter(
                username__startswith=USERNAME_PREFIX,
                is_superuser=False,
            ),
        )

    return counts
