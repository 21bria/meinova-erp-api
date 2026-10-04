"""
Tanggal kepegawaian yang sudah dekat.

Empat jenis, semuanya dari kolom yang sudah lama tersimpan tapi tidak
pernah ada yang menagihnya: masa percobaan, kontrak, ulang tahun, dan
hari jadi kerja.

Dua kelompok dengan sifat berbeda, dan bedanya menentukan cara
menghitungnya:

* **Tanggal sekali seumur** (`probation_end`, `contract_end`) —
  dibandingkan apa adanya, dan yang **sudah lewat tetap ditampilkan**
  selama `keep_overdue_days`. Kontrak yang terlewat justru yang paling
  perlu terlihat: pegawainya masih masuk kerja tanpa dasar kontrak, dan
  menghilangkannya dari layar begitu tanggalnya lewat menghapus
  satu-satunya tanda bahwa ada yang harus dikerjakan.
* **Tanggal berulang** (`birthday`, `work_anniversary`) — yang dicari
  kejadian **berikutnya**, jadi perlu melompat tahun. Yang sudah lewat
  tidak pernah ditampilkan: ulang tahun kemarin bukan pekerjaan yang
  tertunda.

Cakupan datanya kewenangan `RoleAssignment`, sama persis dengan widget
dashboard lain — daftar nama pegawai adalah hal pertama yang bocor
kalau jalur baru lupa menyaringnya.
"""

from __future__ import annotations

from datetime import date

from django.db.models import Q

from apps.accounts.permissions import view_permission_for
from apps.accounts.scoping import DataScopeService
from apps.hr.models import EmployeeReminderPolicy, ReminderKind

from .services import EMPLOYEE_SCOPE, HRDashboardService


LABELS = dict(ReminderKind.choices)


def _next_occurrence(anchor: date, today: date) -> date | None:
    """
    Kejadian berulang berikutnya dari sebuah tanggal acuan.

    29 Februari ditangani dengan menggeser ke 1 Maret pada tahun biasa,
    bukan dilewati: orang yang lahir 29 Februari tetap berulang tahun
    tiap tahun, dan menghilangkannya dari daftar tiga tahun sekali
    adalah bug yang tidak akan pernah dilaporkan siapa pun.
    """
    for year in (today.year, today.year + 1):
        try:
            candidate = anchor.replace(year=year)
        except ValueError:
            candidate = date(year, 3, 1)

        if candidate >= today:
            return candidate

    return None


class EmployeeReminderService:
    @staticmethod
    def employees(context: dict):
        from apps.hr.models import Employee

        queryset = (
            Employee.objects
            .filter(is_active=True, is_deleted=False)
            .select_related(
                "employment",
                "organization__location",
                # Ikut karena `base` di bawah membacanya. Tanpa keduanya
                # tiap pegawai menambah dua query, dan pengingat harian
                # berjalan untuk seluruh pegawai tiap tenant.
                "organization__position",
                "organization__department",
            )
        )

        # **Ketiga filter toolbar, bukan cuma Company.** Widget ini
        # ditulis sebelum filter Location ada, dan sejak itu memilih
        # "Sagea" di toolbar menyempitkan sebelas widget lain sementara
        # daftar pengingat tetap memuat seluruh tenant — termasuk tombol
        # "Lokasi Saya", yang justru dibuat supaya admin site tidak
        # perlu menebak perusahaannya dulu. Selisih seperti itu tidak
        # berbunyi: barisnya tetap keluar, cuma bukan barisnya sendiri.
        #
        # Dipakai ulang dari `HRDashboardService`, bukan disalin: tiga
        # salinan penyaring yang sama adalah persis cara filter baru
        # diam-diam cuma berlaku di sebagian widget.
        queryset = HRDashboardService.apply_filters(
            queryset,
            context,
            prefix="organization__",
        )

        return DataScopeService.filter(
            queryset,
            EMPLOYEE_SCOPE,
            context.get("user"),
            required_permission=view_permission_for(queryset.model),
        )

    # ------------------------------------------------------------------

    @classmethod
    def collect(cls, context: dict, limit: int | None = None) -> dict:
        policy = EmployeeReminderPolicy.resolve()

        today = date.today()

        items: list[dict] = []

        employees = cls.employees(context)

        # Satu queryset untuk semuanya, disaring di Python. Empat query
        # terpisah untuk 4 jenis pada tabel yang sama tidak menghemat
        # apa pun — jumlah pegawai per tenant kecil, dan yang mahal
        # justru join organisasinya.
        rows = list(employees)

        for employee in rows:
            employment = getattr(employee, "employment", None)

            assignment = getattr(employee, "organization", None)

            where = getattr(assignment, "location", None)

            base = {
                "employee_id": employee.id,
                "employee_number": employee.employee_number,
                "name": (
                    employee.display_name
                    or employee.full_name
                    or employee.employee_number
                ),
                "location": str(where) if where else None,
                # Jabatan dan department dipakai isi email pengingat.
                # Kartu pengingat di dashboard tidak menampilkannya dan
                # tidak terganggu oleh kunci tambahan — tapi surat yang
                # cuma menyebut nama membuat penerimanya harus membuka
                # aplikasi hanya untuk tahu ini pegawai unit mana.
                "position": (
                    str(assignment.position)
                    if assignment is not None and assignment.position_id
                    else None
                ),
                "department": (
                    str(assignment.department)
                    if assignment is not None and assignment.department_id
                    else None
                ),
            }

            # --- tanggal sekali seumur ---------------------------------

            once = []

            if policy.probation_enabled and employment is not None:
                once.append(
                    (
                        ReminderKind.PROBATION_END,
                        employment.probation_end,
                        policy.probation_lead_days,
                    )
                )

            if policy.contract_enabled and employment is not None:
                once.append(
                    (
                        ReminderKind.CONTRACT_END,
                        employment.contract_end,
                        policy.contract_lead_days,
                    )
                )

            for kind, when, lead in once:
                if when is None:
                    continue

                days_left = (when - today).days

                if days_left > lead:
                    continue

                if days_left < -policy.keep_overdue_days:
                    continue

                items.append(
                    {
                        **base,
                        "kind": kind,
                        "kind_label": LABELS[kind],
                        "date": when,
                        "days_left": days_left,
                        "is_overdue": days_left < 0,
                    }
                )

            # --- tanggal berulang --------------------------------------

            recurring = []

            if policy.birthday_enabled:
                recurring.append(
                    (
                        ReminderKind.BIRTHDAY,
                        employee.birth_date,
                        policy.birthday_lead_days,
                    )
                )

            if policy.anniversary_enabled and employment is not None:
                recurring.append(
                    (
                        ReminderKind.WORK_ANNIVERSARY,
                        employment.join_date,
                        policy.anniversary_lead_days,
                    )
                )

            for kind, anchor, lead in recurring:
                if anchor is None:
                    continue

                when = _next_occurrence(anchor, today)

                if when is None:
                    continue

                days_left = (when - today).days

                if days_left > lead:
                    continue

                items.append(
                    {
                        **base,
                        "kind": kind,
                        "kind_label": LABELS[kind],
                        "date": when,
                        "days_left": days_left,
                        "is_overdue": False,
                        # Umur / masa kerja yang akan dicapai — itu yang
                        # sebenarnya ingin dibaca orang dari baris ini.
                        "years": when.year - anchor.year,
                    }
                )

        # Yang paling mendesak di atas; yang sudah lewat paling atas
        # lagi, karena itu pekerjaan yang tertunda, bukan yang akan
        # datang.
        items.sort(key=lambda row: (row["days_left"], row["employee_number"]))

        total = len(items)

        if limit:
            items = items[:limit]

        return {
            "items": items,
            "total": total,
            "overdue": sum(1 for row in items if row.get("is_overdue")),
        }
