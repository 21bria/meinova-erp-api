from datetime import time

from django.db import transaction

from apps.administration.models import (
    Shift,
    ShiftGroup,
    WorkSchedule,
    WorkScheduleDay,
)


@transaction.atomic
def seed():
    """
    Seed HR Attendance master data.

    Seluruh `defaults` menyebut `is_deleted: False`, dan itu bukan
    kelebihan menulis. `update_or_create` mencocokkan lewat `code` dan
    ikut menemukan baris yang sudah **di-soft-delete**; tanpa kolom itu
    di `defaults`, baris yang pernah dihapus seseorang dari layar tidak
    pernah hidup lagi walau seed dijalankan berapa kali pun. Sudah
    kejadian: shift `OFFICE-10` dan `SITE` tersimpan sebagai baris
    terhapus, jadi seed melaporkan berhasil sementara dropdown Shift
    tetap tidak memuat keduanya — dan pegawai yang shift-nya kosong
    diam-diam kehilangan seluruh perhitungan keterlambatannya.

    Pengecualiannya `ROS14` di bawah, yang memang sengaja dinonaktifkan
    dan karena itu tidak punya `update_or_create` sama sekali.
    """

    # -------------------------------------------------------------------------
    # Shift Groups
    # -------------------------------------------------------------------------

    office_group, _ = ShiftGroup.objects.update_or_create(
        code="OFFICE",
        defaults={
            "name": "Office Shift",
            "description": "Shift group for office employees.",
            "sort_order": 10,
            "is_active": True,
            "is_deleted": False,
        },
    )

    mining_group, _ = ShiftGroup.objects.update_or_create(
        code="MINING",
        defaults={
            "name": "Mining Shift",
            "description": "Shift group for mining operations.",
            "sort_order": 20,
            "is_active": True,
            "is_deleted": False,
        },
    )

    # -------------------------------------------------------------------------
    # Shifts
    # -------------------------------------------------------------------------

    # Jam kantor yang mulai pukul sepuluh. Pola yang lazim dipakai
    # kantor pusat di Jakarta, dan master shift memang tempatnya
    # menampung beberapa pilihan — bukan satu jam kerja untuk semua.
    #
    # Ini **bukan** angka karangan seperti kuota hari sakit yang pernah
    # ditarik dari seed jatah cuti: shift adalah pilihan yang memang
    # disunting per tenant, bukan klaim tentang aturan yang berlaku.
    office_shift, _ = Shift.objects.update_or_create(
        code="OFFICE-10",
        defaults={
            "name": "Office",
            "description": "Regular office shift 10:00–18:00.",
            "shift_group": office_group,
            "start_time": time(10, 0),
            "end_time": time(18, 0),
            "break_start_time": time(12, 0),
            "break_end_time": time(13, 0),
            "crosses_midnight": False,
            "sort_order": 10,
            "is_active": True,
            "is_deleted": False,
        },
    )

    # Jam lapangan yang berakhir pukul lima. `DAY` (07:00–19:00) adalah
    # shift operasional dua belas jam; site yang jam kerjanya sepuluh
    # jam tidak punya barisnya sendiri, dan memakai `DAY` membuat setiap
    # orang terlihat pulang dua jam lebih awal.
    site_day_shift, _ = Shift.objects.update_or_create(
        code="SITE-DAY",
        defaults={
            "name": "Site Day",
            "description": "Regular site day shift 07:00–17:00.",
            "shift_group": mining_group,
            "start_time": time(7, 0),
            "end_time": time(17, 0),
            "break_start_time": time(12, 0),
            "break_end_time": time(13, 0),
            "crosses_midnight": False,
            "sort_order": 20,
            "is_active": True,
            "is_deleted": False,
        },
    )

    day_shift, _ = Shift.objects.update_or_create(
        code="DAY",
        defaults={
            "name": "Day Shift",
            "description": "Twelve-hour operational day shift.",
            "shift_group": mining_group,
            "start_time": time(7, 0),
            "end_time": time(19, 0),
            "break_start_time": time(12, 0),
            "break_end_time": time(13, 0),
            "crosses_midnight": False,
            "sort_order": 30,
            "is_active": True,
            "is_deleted": False,
        },
    )

    night_shift, _ = Shift.objects.update_or_create(
        code="NIGHT",
        defaults={
            "name": "Night Shift",
            "description": "Twelve-hour operational night shift.",
            "shift_group": mining_group,
            "start_time": time(19, 0),
            "end_time": time(7, 0),
            "break_start_time": time(0, 0),
            "break_end_time": time(1, 0),
            "crosses_midnight": True,
            "sort_order": 40,
            "is_active": True,
            "is_deleted": False,
        },
    )

    # Shift lama yang tidak lagi dipakai seed.
    Shift.objects.filter(
        code__in=["OFFICE", "SITE"],
        is_deleted=False,
    ).update(
        is_active=False,
        is_deleted=True,
    )

    # -------------------------------------------------------------------------
    # Work Schedules
    # -------------------------------------------------------------------------

    regular_schedule, _ = WorkSchedule.objects.update_or_create(
        code="REG5",
        defaults={
            "name": "Regular 5 Days",
            "description": "Monday to Friday office schedule.",
            "schedule_type": WorkSchedule.ScheduleType.WEEKLY,
            "standard_hours_per_day": 8,
            "standard_hours_per_week": 40,
            "work_days": 5,
            "cycle_work_days": None,
            "cycle_off_days": None,
            "is_flexible": False,
            "crosses_midnight": False,
            "sort_order": 10,
            "is_active": True,
            "is_deleted": False,
        },
    )

    # Dua pola roster, keduanya off dua minggu. Disimpan sebagai hari
    # (42/14, 56/14), bukan minggu, supaya panjang siklusnya bisa
    # dipetakan langsung ke tanggal oleh `RotationPeriodGenerator`.
    #
    # Sengaja **hanya dua**. Dropdown Work Schedule sempat berisi enam
    # pola roster yang hampir tidak bisa dibedakan satu sama lain, dan
    # yang pertama dikeluhkan pengguna justru itu — bukan kurangnya
    # pilihan. Pola baru ditambahkan kalau memang ada gelombang yang
    # memakainya, bukan disiapkan untuk berjaga-jaga.
    roster_schedule, _ = WorkSchedule.objects.update_or_create(
        code="ROS42",
        defaults={
            "name": "Roster 6 Weeks On 2 Weeks Off",
            "description": (
                "Forty-two working days followed by fourteen off days."
            ),
            "schedule_type": WorkSchedule.ScheduleType.ROSTER,
            "standard_hours_per_day": 10,
            "standard_hours_per_week": 70,
            "work_days": 42,
            "cycle_work_days": 42,
            "cycle_off_days": 14,
            "is_flexible": False,
            "crosses_midnight": False,
            "sort_order": 30,
            "is_active": True,
            "is_deleted": False,
        },
    )

    roster_56_schedule, _ = WorkSchedule.objects.update_or_create(
        code="ROS56",
        defaults={
            "name": "Roster 8 Weeks On 2 Weeks Off",
            "description": (
                "Fifty-six working days followed by fourteen off days."
            ),
            "schedule_type": WorkSchedule.ScheduleType.ROSTER,
            "standard_hours_per_day": 10,
            "standard_hours_per_week": 70,
            "work_days": 56,
            "cycle_work_days": 56,
            "cycle_off_days": 14,
            "is_flexible": False,
            "crosses_midnight": False,
            "sort_order": 40,
            "is_active": True,
            "is_deleted": False,
        },
    )

    # Pola lama yang pernah diseed dan tidak dipakai gelombang mana pun.
    # Dinonaktifkan, bukan dihapus: `WorkSchedule` dilindungi
    # `on_delete=PROTECT` dari `EmploymentAssignment` dan `RosterCrew`,
    # jadi hard delete akan menggagalkan seed begitu ada satu tenant
    # yang masih menunjuknya.
    WorkSchedule.objects.filter(
        code__in=["ROS14"],
        is_deleted=False,
    ).update(
        is_deleted=True,
        is_active=False,
    )

    # -------------------------------------------------------------------------
    # Regular Schedule Days
    # -------------------------------------------------------------------------

    regular_schedule_day_count = 0

    for weekday in range(
        WorkScheduleDay.Weekday.MONDAY,
        WorkScheduleDay.Weekday.SUNDAY + 1,
    ):
        is_working_day = weekday <= WorkScheduleDay.Weekday.FRIDAY

        WorkScheduleDay.objects.update_or_create(
            work_schedule=regular_schedule,
            weekday=weekday,
            defaults={
                "shift": office_shift if is_working_day else None,
                "is_working_day": is_working_day,
                "start_time": (
                    time(10, 0)
                    if is_working_day
                    else None
                ),
                "end_time": (
                    time(18, 0)
                    if is_working_day
                    else None
                ),
                "break_start_time": (
                    time(12, 0)
                    if is_working_day
                    else None
                ),
                "break_end_time": (
                    time(13, 0)
                    if is_working_day
                    else None
                ),
                "break_minutes": (
                    60
                    if is_working_day
                    else 0
                ),
                "tolerance_in_minutes": (
                    15
                    if is_working_day
                    else 0
                ),
                "tolerance_out_minutes": (
                    15
                    if is_working_day
                    else 0
                ),
            },
        )

        regular_schedule_day_count += 1

    # -------------------------------------------------------------------------
    # Roster Template Days
    # -------------------------------------------------------------------------
    #
    # WorkScheduleDay masih berbasis weekday.
    #
    # Siklus roster aktual sekarang memakai pola 42 hari kerja / 14 hari
    # libur dan 56 hari kerja / 14 hari libur. Panjang siklusnya ditentukan
    # oleh `cycle_work_days` + `cycle_off_days`, sedangkan roster assignment
    # atau shift assignment berdasarkan tanggal menentukan posisi pegawai
    # pada siklus tersebut.
    #
    # Detail di bawah hanya menjadi template default jam kerja operasional.
    # Shift aktual pegawai/site tetap dapat berbeda, misalnya `SITE-DAY`,
    # `DAY`, atau `NIGHT`, sesuai crew/assignment yang berlaku.
    # -------------------------------------------------------------------------

    roster_schedule_day_count = 0

    for schedule in (
        roster_schedule,
        roster_56_schedule,
    ):
        for weekday in range(
            WorkScheduleDay.Weekday.MONDAY,
            WorkScheduleDay.Weekday.SUNDAY + 1,
        ):
            WorkScheduleDay.objects.update_or_create(
                work_schedule=schedule,
                weekday=weekday,
                defaults={
                    "shift": day_shift,
                    "is_working_day": True,
                    "start_time": time(7, 0),
                    "end_time": time(19, 0),
                    "break_start_time": time(12, 0),
                    "break_end_time": time(13, 0),
                    "break_minutes": 60,
                    "tolerance_in_minutes": 15,
                    "tolerance_out_minutes": 15,
                },
            )

            roster_schedule_day_count += 1

    # -------------------------------------------------------------------------
    # Result
    # -------------------------------------------------------------------------

    return {
        "shift_groups": 2,
        "shifts": 4,
        "work_schedules": 3,
        "work_schedule_days": (
            regular_schedule_day_count
            + roster_schedule_day_count
        ),
        "objects": {
            "office_group": office_group,
            "mining_group": mining_group,
            "office_shift": office_shift,
            "site_day_shift": site_day_shift,
            "day_shift": day_shift,
            "night_shift": night_shift,
            "regular_schedule": regular_schedule,
            "roster_schedule": roster_schedule,
            "roster_56_schedule": roster_56_schedule,
        },
    }