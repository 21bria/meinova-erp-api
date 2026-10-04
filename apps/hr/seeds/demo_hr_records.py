"""
Isi untuk widget dashboard HR yang selama ini kosong.

Lima bagian beranda HR — Unit Kerja, Jenjang Pendidikan, Rekap Cuti,
Pelatihan Mendatang, Pengingat Kepegawaian — dibaca dari lima tabel
yang berbeda, dan **tiga di antaranya tidak pernah diisi satu seed pun**
di tenant peragaan: `EmployeeEducation`, `TrainingProgram`, dan
`JobVacancy` semuanya nol baris sejak tenant pertama dibuat. Yang
tampak di layar bukan "belum ada datanya" melainkan chart kosong dan
daftar kosong, dan keduanya tidak bisa dibedakan dari widget yang gagal
memuat — beberapa kali sudah dilaporkan sebagai bug.

Yang diisi di sini sengaja **bukan** yang paling rapi, melainkan yang
paling mewakili keadaan nyata:

* satu pegawai **tanpa** baris pendidikan, supaya irisan "Belum
  Ditentukan" benar-benar terlihat dan HR tahu bentuk tampilannya saat
  datanya memang belum lengkap;
* satu program pelatihan **tanpa company** (induksi K3 se-grup), yang
  membuktikan `allow_null=True` pada cakupan data — program lintas
  perusahaan tidak boleh hilang dari layar admin site;
* satu program yang **sudah lewat**, supaya "Pelatihan Mendatang"
  terbukti menyaring, bukan sekadar menampilkan semua baris;
* lowongan di **dua lokasi**, supaya filter Location di toolbar punya
  sesuatu untuk disaring;
* cuti berstatus `RECORDED` di **beberapa jenis**, supaya Rekap Cuti
  tidak jadi tabel satu baris.

Tanggalnya relatif terhadap **hari ini**, bukan dipatok seperti
`demo_workforce.TODAY`. Alasannya beda keperluan: yang dipatok adalah
data yang diuji angkanya (jatah cuti, rantai approval), sedangkan yang
di sini harus **jatuh di dalam periode berjalan** supaya widgetnya ada
isinya kapan pun seed-nya dijalankan. Pola yang sama dengan
`seed_demo_attendance`.

Aman diulang. Baris pelatihan dan lowongan dicocokkan lewat `code`;
cuti dan lembur ditandai `MARKER` di kolom catatan dan dibuang lebih
dulu — keduanya tidak punya kode, dan menumpuknya tiap seed dijalankan
membuat angka Jam Lembur naik sendiri tanpa ada yang menambahkannya.
"""

from __future__ import annotations

from datetime import date, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.administration.models import Company, Department, Location
from apps.administration.models.references.hr import (
    Degree,
    Education,
    EmploymentType,
    LeaveType,
    OvertimeType,
    StudyField,
    TrainingCategory,
    TrainingProvider,
)
from apps.hr.api.leave.services import EmployeeLeaveService
from apps.hr.api.overtime.services import EmployeeOvertimeService
from apps.hr.models import (
    Employee,
    EmployeeEducation,
    EmployeeLeave,
    EmployeeOvertime,
    JobVacancy,
    LeaveStatus,
    OvertimeStatus,
    ParticipantStatus,
    TrainingParticipant,
    TrainingProgram,
    TrainingProgramStatus,
    VacancyStatus,
)


# Penanda baris buatan seed ini. Dipakai untuk membuang jejaknya sebelum
# menulis ulang — bukan sebagai gaya penulisan catatan.
MARKER = "[data uji hr]"

# Awalan kode. Dipisahkan dari data klien supaya perintah ini tidak akan
# pernah menyentuh program pelatihan atau lowongan sungguhan walau
# dijalankan di tenant yang salah.
TRAINING_PREFIX = "DEMO-TRN-"
VACANCY_PREFIX = "DEMO-VAC-"

COMPANY_CODE = "MMR"
HO_LOCATION_CODE = "JKT-HO"
SITE_LOCATION_CODE = "SAGEA-MINE"


# ----------------------------------------------------------------------
# Pendidikan
# ----------------------------------------------------------------------
#
# **HO004 sengaja tidak ada di daftar ini.** Satu pegawai tanpa riwayat
# pendidikan adalah keadaan yang paling lazim di tenant yang datanya
# baru dipindahkan, dan chart yang tidak pernah memperlihatkannya
# membuat orang menyangka angka di layar sudah mencakup semua orang.
#
# (nomor: (jenjang, gelar, bidang, institusi, tahun lulus, IPK))
EDUCATIONS = {
    "HO001": ("S2", None, "MANAGEMENT", "Universitas Indonesia", 2011, "3.71"),
    "HO002": ("S1", "SE", "MANAGEMENT", "Universitas Padjadjaran", 2015, "3.42"),
    "HO003": ("S1", "SE", "ACCOUNTING", "Universitas Brawijaya", 2021, "3.36"),
    "HO005": ("S2", None, "ACCOUNTING", "Universitas Gadjah Mada", 2010, "3.80"),

    "SGA001": ("S1", "ST", "MINING", "Institut Teknologi Bandung", 2012, "3.28"),
    "SGA002": ("S1", "ST", "GEOLOGY", "UPN Veteran Yogyakarta", 2018, "3.15"),
    "SGA003": ("D3", "AMD", "MANAGEMENT", "Politeknik Negeri Ambon", 2021, "3.05"),
    "SGA004": ("S1", "SE", "MANAGEMENT", "Universitas Hasanuddin", 2014, "3.51"),
    "SGA005": ("S2", "MT", "MINING", "Institut Teknologi Bandung", 2016, "3.66"),
    "SGA006": ("SMA", None, None, "SMA Negeri 1 Weda", 2019, None),
}


# ----------------------------------------------------------------------
# Pelatihan
# ----------------------------------------------------------------------
#
# `company=None` pada induksi K3 bukan kelalaian: program se-grup memang
# tidak menempel ke satu perusahaan, dan itu yang membuat
# `TRAINING_SCOPE` dipanggil dengan `allow_null=True`. Kalau seluruh
# program bercompany, cabang itu tidak pernah terlewati oleh siapa pun
# yang mencoba layarnya.
#
# (kode, nama, kategori, provider, company?, offset mulai, lama hari,
#  kuota, status, peserta)
TRAININGS = [
    (
        "INDUKSI", "Induksi K3 Pertambangan",
        "SAFETY_IND", "INTERNAL", None,
        7, 1, 25, TrainingProgramStatus.PLANNED,
        ["SGA006", "SGA003", "HO004"],
    ),
    (
        "P3K", "Pertolongan Pertama pada Kecelakaan (P3K)",
        "FIRST_AID", "PJK3", COMPANY_CODE,
        21, 2, 15, TrainingProgramStatus.PLANNED,
        ["SGA002", "SGA004", "SGA005", "HO002"],
    ),
    (
        "DEFDRIVE", "Defensive Driving — Area Tambang",
        "DEF_DRIVE", "MSI", COMPANY_CODE,
        45, 2, 12, TrainingProgramStatus.PLANNED,
        ["SGA001", "SGA002"],
    ),
    # Sudah lewat, dan itu gunanya: "Pelatihan Mendatang" harus terbukti
    # menyaring. Program yang selesai tetap terlihat di layar Training,
    # cuma tidak di widget beranda.
    (
        "MINESAFE", "Mine Safety Refresher",
        "MINE_SAFE", "BNSP", COMPANY_CODE,
        -30, 2, 20, TrainingProgramStatus.COMPLETED,
        ["SGA001", "SGA002", "SGA005"],
    ),
]


# ----------------------------------------------------------------------
# Lowongan
# ----------------------------------------------------------------------
#
# Dua lokasi, karena satu lokasi tidak membuktikan apa pun tentang
# filter Location di toolbar.
#
# (kode, judul, lokasi, department, tipe, kuota, offset buka,
#  offset tutup?, status)
VACANCIES = [
    (
        "MINE-ENG", "Mining Engineer",
        SITE_LOCATION_CODE, "ENG", "PERM", 2,
        -45, 30, VacancyStatus.OPEN,
    ),
    (
        "HR-OFF", "HR Officer",
        HO_LOCATION_CODE, "HRD", "PERM", 1,
        -20, 40, VacancyStatus.OPEN,
    ),
    (
        "MECH", "Heavy Equipment Mechanic",
        SITE_LOCATION_CODE, "PLANT", "CONT", 3,
        -10, None, VacancyStatus.OPEN,
    ),
    (
        "FIN-STAFF", "Finance Staff",
        HO_LOCATION_CODE, "FIN", "PERM", 1,
        -120, -30, VacancyStatus.CLOSED,
    ),
]


# ----------------------------------------------------------------------
# Lembur
# ----------------------------------------------------------------------
#
# Offset dihitung dari **awal bulan berjalan**, bukan dari hari ini:
# kartu Jam Lembur menjumlahkan seluruh periode terpilih, dan baris yang
# semuanya jatuh di hari-hari terakhir membuat perbandingan dengan bulan
# lalu tidak berarti apa-apa.
#
# (nomor, offset hari, tipe, jam mulai, jam selesai, alasan)
OVERTIMES = [
    ("HO003", 1, "WEEKDAY", time(18, 0), time(21, 0), "Tutup buku bulanan"),
    ("HO003", 8, "WEEKDAY", time(18, 0), time(20, 30), "Tutup buku bulanan"),
    ("HO002", 2, "WEEKDAY", time(18, 0), time(20, 0), "Rekap absensi"),
    ("HO005", 5, "WEEKEND", time(9, 0), time(14, 0), "Audit internal"),
    ("SGA002", 3, "WEEKDAY", time(17, 0), time(20, 0), "Blasting susulan"),
    ("SGA002", 9, "HOLIDAY", time(8, 0), time(15, 0), "Perbaikan jalan hauling"),
    ("SGA001", 4, "WEEKDAY", time(17, 0), time(19, 30), "Serah terima shift"),
    ("SGA006", 6, "WEEKDAY", time(17, 0), time(19, 0), "Rekap presensi site"),
    ("SGA005", 11, "WEEKEND", time(8, 0), time(13, 0), "Inspeksi K3"),
]


# ----------------------------------------------------------------------
# Cuti tercatat
# ----------------------------------------------------------------------
#
# Berstatus `RECORDED` — cuti yang sudah terjadi dan diketik HR, bukan
# pengajuan. Yang lewat alur pengajuan sudah dipegang
# `seed_demo_workflow`; keduanya berdampingan di satu tabel dan
# dashboard menjumlahkan dua-duanya.
#
# Beberapa jenis sengaja, supaya Rekap Cuti tidak jadi tabel satu baris
# berjudul "Cuti Tahunan".
#
# (nomor, jenis, offset mulai dari awal bulan, lama hari kalender)
LEAVES = [
    ("HO002", "SICK", 4, 2),
    ("HO005", "ANNUAL", 10, 5),
    ("HO001", "BEREAVEMENT", 5, 2),
    ("HO004", "PATERNITY", 12, 2),
    ("SGA004", "ANNUAL", 2, 5),
    ("SGA001", "MARRIAGE", 16, 3),
    ("SGA005", "SICK", 19, 2),
    ("SGA003", "ANNUAL", 21, 4),
]


# ----------------------------------------------------------------------
# Helper
# ----------------------------------------------------------------------


def _by_code(model, code: str | None):
    if not code:
        return None

    return model.objects.filter(code=code, is_deleted=False).first()


def _employees() -> dict[str, Employee]:
    return {
        employee.employee_number: employee
        for employee in Employee.objects.filter(is_deleted=False)
        .select_related("organization")
    }


def _month_start(today: date) -> date:
    return today.replace(day=1)


# ----------------------------------------------------------------------
# Bagian per bagian
# ----------------------------------------------------------------------


def _seed_educations(people: dict[str, Employee], log) -> int:
    written = 0

    for number, row in EDUCATIONS.items():
        employee = people.get(number)

        if employee is None:
            continue

        level, degree, field, institution, year, gpa = row

        education = _by_code(Education, level)

        if education is None:
            log(f"    ! jenjang {level} tidak ada di master, dilewati")
            continue

        EmployeeEducation.objects.update_or_create(
            employee=employee,
            education=education,
            defaults={
                "degree": _by_code(Degree, degree),
                "study_field": _by_code(StudyField, field),
                "institution_name": institution,
                "graduation_year": year,
                "gpa": gpa,
                "is_highest_education": True,
                "is_active": True,
                "is_deleted": False,
                "notes": MARKER,
            },
        )

        written += 1

    log(f"    pendidikan          {written}")

    return written


def _seed_trainings(people: dict[str, Employee], today: date, log) -> int:
    company = _by_code(Company, COMPANY_CODE)

    written = 0
    participants = 0

    for row in TRAININGS:
        (
            suffix, name, category, provider, company_code,
            offset, length, quota, status, members,
        ) = row

        start = today + timedelta(days=offset)

        program, _ = TrainingProgram.objects.update_or_create(
            code=f"{TRAINING_PREFIX}{suffix}",
            defaults={
                "name": name,
                "training_category": _by_code(TrainingCategory, category),
                "provider": _by_code(TrainingProvider, provider),
                "company": company if company_code else None,
                "start_date": start,
                "end_date": start + timedelta(days=length - 1),
                "duration_hours": length * 8,
                "venue": (
                    "Ruang Training Site Sagea"
                    if suffix != "P3K"
                    else "Hotel Santika Ternate"
                ),
                "quota": quota,
                "status": status,
                "is_deleted": False,
                "description": MARKER,
            },
        )

        written += 1

        for number in members:
            employee = people.get(number)

            if employee is None:
                continue

            # Program yang sudah selesai dicatat hadir beserta nilainya;
            # yang belum jalan berhenti di "terdaftar". Menandai peserta
            # program bulan depan sebagai hadir membuat kolom Status di
            # layar Training tidak pernah bisa dipercaya.
            done = status == TrainingProgramStatus.COMPLETED

            TrainingParticipant.objects.update_or_create(
                program=program,
                employee=employee,
                defaults={
                    "status": (
                        ParticipantStatus.ATTENDED
                        if done
                        else ParticipantStatus.REGISTERED
                    ),
                    "score": "82.00" if done else None,
                    "is_passed": True if done else None,
                    "is_deleted": False,
                    "notes": MARKER,
                },
            )

            participants += 1

    log(f"    program pelatihan   {written} ({participants} peserta)")

    return written


def _seed_vacancies(today: date, log) -> int:
    company = _by_code(Company, COMPANY_CODE)

    if company is None:
        log("    ! company MMR tidak ada, lowongan dilewati")
        return 0

    written = 0

    for row in VACANCIES:
        (
            suffix, title, location_code, department_code,
            employment_type, quota, open_offset, close_offset, status,
        ) = row

        location = (
            Location.objects
            .filter(
                code=location_code,
                company=company,
                is_deleted=False,
            )
            .first()
        )

        department = (
            Department.objects
            .filter(
                code=department_code,
                company=company,
                is_deleted=False,
            )
            .first()
        )

        JobVacancy.objects.update_or_create(
            code=f"{VACANCY_PREFIX}{suffix}",
            defaults={
                "title": title,
                "company": company,
                "location": location,
                "department": department,
                "employment_type": _by_code(EmploymentType, employment_type),
                "quota": quota,
                "open_date": today + timedelta(days=open_offset),
                "close_date": (
                    today + timedelta(days=close_offset)
                    if close_offset is not None
                    else None
                ),
                "status": status,
                "is_deleted": False,
                "description": MARKER,
            },
        )

        written += 1

    log(f"    lowongan            {written}")

    return written


def _seed_overtimes(
    people: dict[str, Employee],
    today: date,
    log,
) -> int:
    start_of_month = _month_start(today)

    written = 0
    skipped = 0

    for number, offset, type_code, start, end, reason in OVERTIMES:
        employee = people.get(number)

        if employee is None:
            continue

        work_date = start_of_month + timedelta(days=offset)

        # Hari yang belum terjadi tidak dicatat: lembur yang tertulis
        # untuk minggu depan terbaca sebagai kesalahan input, bukan
        # sebagai data uji.
        if work_date > today:
            skipped += 1
            continue

        try:
            EmployeeOvertimeService.create(
                data={
                    "employee": employee,
                    "overtime_type": _by_code(OvertimeType, type_code),
                    "work_date": work_date,
                    "start_time": start,
                    "end_time": end,
                    "status": OvertimeStatus.RECORDED,
                    "reason": reason,
                    "notes": MARKER,
                },
                user=None,
            )
        except ValidationError as error:
            log(f"    ! lembur {number} {work_date}: {error}")
            skipped += 1
            continue

        written += 1

    log(f"    lembur              {written}" + (
        f" ({skipped} dilewati)" if skipped else ""
    ))

    return written


def _seed_leaves(people: dict[str, Employee], today: date, log) -> int:
    start_of_month = _month_start(today)

    written = 0
    skipped = 0

    for number, type_code, offset, length in LEAVES:
        employee = people.get(number)

        if employee is None:
            continue

        leave_type = _by_code(LeaveType, type_code)

        if leave_type is None:
            log(f"    ! jenis cuti {type_code} tidak ada di master")
            skipped += 1
            continue

        start = start_of_month + timedelta(days=offset)

        try:
            EmployeeLeaveService.create(
                data={
                    "employee": employee,
                    "leave_type": leave_type,
                    "start_date": start,
                    "end_date": start + timedelta(days=length - 1),
                    "status": LeaveStatus.RECORDED,
                    "notes": f"{MARKER} cuti tercatat",
                },
                user=None,
            )
        except ValidationError as error:
            # Bentrok dengan cuti buatan seed lain adalah keadaan yang
            # sah — yang salah tanggalnya di daftar ini, bukan datanya.
            # Dilaporkan, bukan dijatuhkan: sembilan baris lain tidak
            # boleh hilang karena satu tanggal yang tumpang tindih.
            log(f"    ! cuti {number} {start}: {error}")
            skipped += 1
            continue

        written += 1

    log(f"    cuti tercatat       {written}" + (
        f" ({skipped} dilewati)" if skipped else ""
    ))

    return written


# ----------------------------------------------------------------------
# Pembersihan
# ----------------------------------------------------------------------


def _clear(log) -> None:
    """
    Membuang jejak seed ini sebelum menulis ulang.

    Hanya cuti dan lembur — keduanya tidak punya kode, jadi
    `update_or_create` tidak bisa dipakai dan menumpuknya membuat angka
    Jam Lembur naik sendiri tiap seed dijalankan. Pelatihan, lowongan,
    dan pendidikan dicocokkan lewat kunci alaminya dan tidak perlu
    dibuang.

    Hard delete: baris bertanda terhapus tetap menempati kunci uniknya
    (`(employee, work_date)` pada lembur) dan justru menggagalkan
    penulisan berikutnya.
    """
    for label, queryset in (
        ("cuti", EmployeeLeave.objects.filter(notes__startswith=MARKER)),
        ("lembur", EmployeeOvertime.objects.filter(notes__startswith=MARKER)),
    ):
        removed = queryset.count()

        queryset.delete()

        if removed:
            log(f"    (buang {removed} baris {label} lama)")


# ----------------------------------------------------------------------


@transaction.atomic
def run(*, log=print) -> dict:
    today = date.today()

    people = _employees()

    if not people:
        log("  Belum ada pegawai data uji — jalankan seed_demo_workforce.")
        return {}

    log("  Menulis data uji dashboard HR:")

    _clear(log)

    counts = {
        "educations": _seed_educations(people, log),
        "trainings": _seed_trainings(people, today, log),
        "vacancies": _seed_vacancies(today, log),
        "overtimes": _seed_overtimes(people, today, log),
        "leaves": _seed_leaves(people, today, log),
    }

    return counts
