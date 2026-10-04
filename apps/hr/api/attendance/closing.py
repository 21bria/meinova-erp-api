"""
Penutup hari presensi: hari terjadwal yang tidak ada tap-nya.

Yang ditutupnya lubang yang membuat angka kehadiran tidak pernah bisa
turun. Di sistem ini **ketidakhadiran bukan sebuah baris — ia adalah
baris yang tidak ada**: mesin fingerprint hanya mengirim tap, jadi orang
yang tidak masuk tidak menghasilkan apa pun. `AttendanceStatus.ABSENT`
sudah lama ada di enum dan divalidasi di dua tempat, tapi tidak ada satu
baris kode pun yang menulisnya — jadi pembilang selalu sama dengan
penyebut dan "Tingkat Kehadiran" berbunyi 100% selamanya, di data uji
maupun di data klien.

Dan bukan cuma demi dashboard: HR perlu **melihat** siapa yang tidak
hadir di layar Attendance, bukan menyimpulkannya dari baris yang hilang.
Daftar yang benar tidak bisa disusun dari ketiadaan.

Empat keputusan yang membentuknya
---------------------------------
**Hari ini tidak ditutup.** Bawaannya berhenti kemarin — orang yang
belum menekan mesin jam sembilan pagi bukan mangkir, dia belum datang.
Menutup hari berjalan berarti menerbitkan tuduhan yang terbantah
sendiri beberapa jam kemudian.

**Cuti yang sudah disetujui bukan mangkir.** Hari yang tertutup dokumen
cuti berstatus RECORDED/APPROVED ditulis `leave`, bukan `absent`. Kalau
tidak, setiap orang yang mengambil haknya terhitung bolos — dan
justru unit yang tertib administrasinya yang angkanya paling jelek.

**Business Trip yang disetujui bukan mangkir (BT-3).** Hari terjadwal
tanpa tap yang diizinkan perjalanan dinas ditulis `business_trip`
beserta FK perjalanannya — tanpa jam masuk/keluar, tanpa jam kerja,
tanpa lembur. Itu izin kerja di luar lokasi yang dibayar, **bukan**
hadir fisik. Urutannya: cuti → izin sehari penuh → perjalanan → alpa.
Izin sehari penuh tetap ditulis `absent` (dibebaskan resolver izin),
persis seperti sebelumnya, karena izin menang atas perjalanan. Tap
fisik tidak pernah sampai ke sini: hari yang sudah punya baris tidak
disentuh.

**Tidak pernah menimpa.** Hanya hari yang benar-benar tidak punya baris
yang diisi. Baris yang sudah ada — hasil tap, import, atau koreksi
tangan — tidak disentuh sama sekali, jadi perintah ini aman diulang
berapa kali pun.

**Yang ditulis ditandai.** `source=SYSTEM` plus `external_id`
berawalan `CLOSE-`, supaya baris kesimpulan bisa dibedakan dari baris
yang benar-benar berasal dari mesin. Tanpa penanda itu, "tidak hadir"
hasil hitungan sistem tidak bisa dipisahkan dari "tidak hadir" yang
diketik atasannya.

Dan satu cakupan, bukan satu kelayakan
--------------------------------------
`close(employees=...)` menyempitkan **pekerjaan** ke pegawai yang
disebut pemanggil. Bawaannya `None` — seluruh pegawai, persis seperti
sebelum parameter ini ada.

Dibutuhkan karena `company` dan `location` tidak selalu bisa memisahkan
dua kelompok yang memang perlu dipisahkan: data uji lama dan pegawai
sungguhan bisa duduk di company dan lokasi yang sama persis, dan
penutup hari yang tidak bisa dibatasi akan menerbitkan mangkir untuk
keduanya.

Yang parameter ini **bukan**: ia tidak menjawab siapa yang punya
kewajiban presensi. Itu tetap milik Feature Applicability, tanggal
masuk/berhenti, hari pemulihan, dan segmen roster — dan tidak satu pun
dari itu berubah karena pemanggil menyebut daftar pegawai.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q

from apps.hr.api.attendance.schedule import scheduled_work_days
from apps.hr.api.attendance.services import EmployeeAttendanceService
from apps.hr.api.business_trip.coverage import business_trip_days
from apps.hr.applicability import HRFeature, filter_employees
from apps.hr.models import (
    BusinessTrip,
    Employee,
    EmployeeAttendance,
    EmployeeLeave,
    LEAVE_DEDUCTING_STATUSES,
)
from apps.hr.models.attendance.choices import (
    AttendanceApprovalStatus,
    AttendanceSource,
    AttendanceStatus,
)


EXTERNAL_PREFIX = "CLOSE-"


def _employee_ids(employees) -> set[int]:
    """
    Himpunan id dari apa pun yang dioper pemanggil.

    Menerima instance `Employee` maupun id mentah, karena kedua bentuk
    itu yang benar-benar dipegang pemanggil: service lain sudah
    memegang objeknya, perintah baris perintah baru saja
    menerjemahkan nomor pegawai jadi id.

    Himpunan, bukan daftar: menyebut satu pegawai dua kali adalah salah
    ketik, bukan permintaan mengerjakannya dua kali.
    """
    return {
        int(getattr(employee, "pk", employee))
        for employee in employees
    }


class AttendanceClosingService:
    @staticmethod
    def default_until() -> date:
        from django.utils import timezone

        return timezone.localdate() - timedelta(days=1)

    @staticmethod
    def _employees(*, company=None, location=None, employees=None):
        queryset = (
            Employee.objects
            .filter(is_deleted=False)
            .select_related(
                "organization__company",
                "organization__location",
                "employment__employee_group",
                "employment__roster_crew__work_schedule",
                "employment__working_calendar",
            )
            .order_by("employee_number")
        )

        # `scheduled_work_days()` sudah mengembalikan himpunan kosong
        # untuk mereka, jadi barisnya memang tidak akan terbit. Dibuang
        # juga di sini supaya penutup hari tidak menarik dan memutar
        # ratusan pegawai yang sudah pasti nol — dan supaya "berapa
        # pegawai yang diproses" pada ringkasan penutupan menyebut angka
        # yang sebenarnya.
        queryset = filter_employees(queryset, HRFeature.ATTENDANCE)

        if company is not None:
            queryset = queryset.filter(organization__company_id=company)

        if location is not None:
            queryset = queryset.filter(organization__location_id=location)

        # Cakupan pegawai yang **disebut pemanggil**. Menyempit, tidak
        # pernah melebar: penyaring company/location di atas tetap
        # berlaku, jadi cakupan eksplisit tidak bisa dipakai menarik
        # pegawai dari luar batas yang sudah diminta.
        #
        # `pk__in` juga yang membuat id kembar tidak menghasilkan
        # pekerjaan kembar — himpunan id, bukan daftar, dan queryset
        # tetap mengembalikan satu baris per pegawai.
        if employees is not None:
            queryset = queryset.filter(pk__in=_employee_ids(employees))

        return queryset

    @staticmethod
    def _leave_days(employees, start: date, end: date) -> dict[int, set[date]]:
        """
        Tanggal yang tertutup dokumen cuti, per pegawai.

        Satu query untuk seluruh rentang, bukan satu per hari: rentang
        sebulan dikali ratusan pegawai membuat pemeriksaan per baris
        menghasilkan ribuan query untuk jawaban yang bentuknya kecil.
        """
        rows = (
            EmployeeLeave.objects
            .filter(
                employee__in=employees,
                is_deleted=False,
                status__in=LEAVE_DEDUCTING_STATUSES,
                start_date__lte=end,
                end_date__gte=start,
            )
            .values_list("employee_id", "start_date", "end_date")
        )

        result: dict[int, set[date]] = {}

        for employee_id, leave_start, leave_end in rows:
            current = max(leave_start, start)
            last = min(leave_end, end)

            days = result.setdefault(employee_id, set())

            while current <= last:
                days.add(current)
                current += timedelta(days=1)

        return result

    @staticmethod
    def _full_day_permission_days(
        employees,
        start: date,
        end: date,
    ) -> dict[int, set[date]]:
        """
        Tanggal yang tertutup izin sehari penuh yang disetujui.

        Dibaca hanya supaya perjalanan dinas **tidak** menang atas izin:
        pegawai yang minta izin sehari penuh di tengah perjalanannya
        tidak sedang bertugas hari itu.
        """
        from apps.hr.models.attendance.permission import (
            AttendancePermission,
            AttendancePermissionType,
            PERMISSION_EFFECTIVE_STATUSES,
        )

        rows = (
            AttendancePermission.objects
            .filter(
                employee__in=employees,
                is_deleted=False,
                permission_type=AttendancePermissionType.FULL_DAY,
                status__in=PERMISSION_EFFECTIVE_STATUSES,
                date__gte=start,
                date__lte=end,
            )
            .values_list("employee_id", "date")
        )

        result: dict[int, set[date]] = {}

        for employee_id, day in rows:
            result.setdefault(employee_id, set()).add(day)

        return result

    @classmethod
    @transaction.atomic
    def close(
        cls,
        *,
        start: date | None = None,
        end: date | None = None,
        company=None,
        location=None,
        employees=None,
        user=None,
        dry_run: bool = False,
        log=None,
    ) -> dict:
        """
        `employees` **menyempitkan** cakupan, dan bawaannya `None`.

        `None` berarti "seperti sebelumnya": seluruh pegawai yang lolos
        Feature Applicability, disaring company/location kalau disebut.
        Pemanggil lama tidak berubah perilakunya sama sekali.

        Yang **bukan** `None` adalah cakupan yang disebut terang-
        terangan — termasuk daftar kosong. Daftar kosong berarti **tidak
        ada pegawai yang diminta**, jadi tidak ada satu baris pun yang
        ditulis. Menerjemahkannya jadi "semua" adalah cara paling pelan
        untuk membuat satu bug cakupan menutup seluruh tenant: hari yang
        salah ditutup tidak berbunyi apa-apa, ia cuma menerbitkan
        mangkir yang baru ketahuan waktu gaji dibayarkan.

        Yang **tidak** diubah parameter ini: siapa yang punya kewajiban
        presensi. Feature Applicability, tanggal masuk/berhenti, hari
        pemulihan, dan segmen roster tetap satu-satunya yang menjawab
        itu. Ini cakupan pekerjaan, bukan kelayakan.
        """
        end = end or cls.default_until()
        start = start or end.replace(day=1)

        if start > end:
            raise ValueError(
                "Tanggal mulai tidak boleh melewati tanggal akhir.",
            )

        # Cakupan kosong yang **disebut** berhenti di sini, sebelum
        # query mana pun. Kalau diteruskan, `pk__in=set()` memang
        # menghasilkan nol baris juga — tapi jawabannya lahir dari
        # kebetulan ORM, dan kebetulan tidak bisa diandalkan menjaga
        # seluruh tenant.
        if employees is not None and not _employee_ids(employees):
            return {
                "start": start,
                "end": end,
                "employees": 0,
                "absent": 0,
                "leave": 0,
                "business_trip": 0,
                "scanned": 0,
            }

        selected = list(
            cls._employees(
                company=company,
                location=location,
                employees=employees,
            ),
        )

        if not selected:
            return {
                "start": start,
                "end": end,
                "employees": 0,
                "absent": 0,
                "leave": 0,
                "business_trip": 0,
                "scanned": 0,
            }

        # Baris yang sudah ada, sekali ambil. Yang soft-deleted sengaja
        # tidak dihitung ada: constraint uniknya pun dikondisikan ke
        # `is_deleted=False`, jadi menganggapnya ada akan membuat hari
        # itu tidak pernah bisa ditutup lagi setelah barisnya dihapus.
        existing = set(
            EmployeeAttendance.objects
            .filter(
                employee__in=selected,
                work_date__gte=start,
                work_date__lte=end,
                is_deleted=False,
            )
            .values_list("employee_id", "work_date")
        )

        on_leave = cls._leave_days(selected, start, end)
        on_permission = cls._full_day_permission_days(selected, start, end)
        on_trip = business_trip_days(selected, start, end)

        trips = BusinessTrip.objects.in_bulk(
            {trip_id for days in on_trip.values() for trip_id in days.values()},
        )

        absent = 0
        leave = 0
        trip_days = 0
        scanned = 0

        for employee in selected:
            days = scheduled_work_days(employee, start, end)

            scanned += len(days)

            missing = sorted(
                day
                for day in days
                if (employee.id, day) not in existing
            )

            if not missing:
                continue

            employee_leave = on_leave.get(employee.id, set())
            employee_permission = on_permission.get(employee.id, set())
            employee_trip = on_trip.get(employee.id, {})

            for day in missing:
                trip = None

                # Cuti → izin sehari penuh → perjalanan → alpa.
                if day in employee_leave:
                    status = AttendanceStatus.LEAVE
                    notes = (
                        "Ditutup otomatis: hari terjadwal tanpa "
                        "catatan kehadiran."
                    )
                    leave += 1

                elif (
                    day in employee_trip
                    and day not in employee_permission
                ):
                    status = AttendanceStatus.BUSINESS_TRIP
                    trip = trips.get(employee_trip[day])
                    notes = (
                        "Ditutup otomatis: hari terjadwal tanpa tap, "
                        "diizinkan Business Trip. Bukan hadir fisik."
                    )
                    trip_days += 1

                else:
                    status = AttendanceStatus.ABSENT
                    notes = (
                        "Ditutup otomatis: hari terjadwal tanpa "
                        "catatan kehadiran."
                    )
                    absent += 1

                if dry_run:
                    continue

                EmployeeAttendanceService.create(
                    data={
                        "employee": employee,
                        "work_date": day,
                        "status": status,
                        "business_trip": trip,
                        "source": AttendanceSource.SYSTEM,
                        "approval_status": AttendanceApprovalStatus.DRAFT,
                        "worked_minutes": 0,
                        "external_id": (
                            f"{EXTERNAL_PREFIX}{employee.employee_number}-"
                            f"{day.strftime('%Y%m%d')}"
                        ),
                        "notes": notes,
                    },
                    user=user,
                )

            if log is not None:
                log(
                    f"  {employee.employee_number} "
                    f"{employee.full_name}: {len(missing)} hari"
                )

        return {
            "start": start,
            "end": end,
            "employees": len(selected),
            "absent": absent,
            "leave": leave,
            "business_trip": trip_days,
            "scanned": scanned,
        }
