"""
Pengingat tanggal kepegawaian → baris notifikasi.

Perhitungannya tidak diulang di sini: `EmployeeReminderService.collect`
sudah menghasilkan daftar yang sama persis dengan yang tampil di
dashboard HR. Kalau angkanya dihitung dua kali dengan dua potong kode,
belnya dan dashboardnya akan berbeda pada hari yang tanggalnya di
perbatasan ambang, dan tidak akan ada yang tahu mana yang benar.

**Penerimanya dihitung per orang, bukan per pengingat.** `collect()`
menerima `context["user"]` dan menyaring pegawainya lewat
cakupan data, jadi cukup dijalankan sekali untuk tiap calon
penerima dan hasilnya sudah menjadi haknya masing-masing. Menyusunnya
terbalik — mendaftar pengingat lebih dulu lalu mencari siapa yang boleh
melihatnya — berarti menulis ulang seluruh logika cakupan di sini.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import get_user_model

from apps.administration.api.notification.services.notification_service import (
    NotificationService,
)
from apps.hr.models import EmployeeReminderPolicy, ReminderKind

from .reminders import EmployeeReminderService

logger = logging.getLogger(__name__)


# Jenis yang pantas dikirim ke pegawainya sendiri. Ulang tahun dan hari
# jadi kerja sengaja di luar daftar: itu pengingat **untuk HR** supaya
# ada yang mengucapkan, bukan pemberitahuan kepada orang yang sudah tahu
# kapan ia lahir.
SELF_KINDS = {
    ReminderKind.PROBATION_END,
    ReminderKind.CONTRACT_END,
}

TYPE_BY_KIND = {
    ReminderKind.PROBATION_END: "WARNING",
    ReminderKind.CONTRACT_END: "WARNING",
    ReminderKind.BIRTHDAY: "INFO",
    ReminderKind.WORK_ANNIVERSARY: "INFO",
}


def _phrase(days_left: int) -> str:
    """
    Sisa hari sebagai kalimat.

    Bahasa Inggris, mengikuti seluruh teks yang dibaca pengguna di
    aplikasi ini — judul kolom, menu, tombol. Judul notifikasi memakai
    label jenis (`Contract End`) yang memang sudah Inggris, jadi
    menuliskan sisa harinya dalam Bahasa Indonesia menghasilkan satu
    kalimat dua bahasa.
    """
    if days_left < 0:
        days = abs(days_left)

        return f"overdue by {days} day{'s' if days > 1 else ''}"

    if days_left == 0:
        return "today"

    if days_left == 1:
        return "tomorrow"

    return f"in {days_left} days"


class EmployeeReminderNotifier:
    """Menulis baris notifikasi dari pengingat yang jatuh tempo."""

    @staticmethod
    def hr_recipients():
        """
        Pemegang role penerima pengingat.

        Superuser **tidak** ikut otomatis. Akun superuser sering dipakai
        bergantian oleh developer dan implementor, dan mengisi belnya
        dengan pengingat kontrak seluruh tenant membuat bel itu tidak
        bisa dipakai untuk apa pun. Yang mau menerima, beri role-nya.
        """
        User = get_user_model()

        return list(
            User.objects
            .filter(
                is_active=True,
                roles__code__in=settings.HR_REMINDER_ROLES,
                roles__is_deleted=False,
            )
            .distinct()
        )

    # ------------------------------------------------------------------

    @classmethod
    def _title(cls, item: dict) -> str:
        when = _phrase(item["days_left"])

        if item["kind"] == ReminderKind.BIRTHDAY:
            return f"{item['name']} has a birthday {when}"

        if item["kind"] == ReminderKind.WORK_ANNIVERSARY:
            years = item.get("years")

            return (
                f"{item['name']}"
                f"{f' celebrates {years} years' if years else ' has a work anniversary'}"
                f" {when}"
            )

        # "Contract End" / "Probation End" datang dari `ReminderKind`,
        # jadi judulnya ikut berubah kalau labelnya diganti — bukan
        # kalimat kedua yang harus diingat orang untuk disamakan.
        return f"{item['kind_label']}: {item['name']} — {when}"

    @classmethod
    def _message(cls, item: dict) -> str:
        parts = [item["date"].strftime("%d %B %Y")]

        if item.get("employee_number"):
            parts.append(item["employee_number"])

        if item.get("location"):
            parts.append(item["location"])

        return " · ".join(parts)

    # ------------------------------------------------------------------

    @classmethod
    def _push(cls, user, item, *, dry_run: bool) -> bool:
        if dry_run:
            return True

        result = NotificationService.push(
            user,
            title=cls._title(item),
            message=cls._message(item),
            type=TYPE_BY_KIND.get(item["kind"], "INFO"),
            module="hr",
            link=f"/hr/employees/{item['employee_id']}",
            # Jenisnya ikut jadi kunci dedup. Tanpa itu, pengingat
            # kontrak dan pengingat ulang tahun orang yang sama saling
            # menimpa — dan yang muncul di bel tinggal salah satunya,
            # tergantung mana yang diperiksa belakangan.
            object_type=f"employee-{item['kind']}",
            object_id=item["employee_id"],
        )

        # `push()` mengembalikan None kalau orangnya mematikan
        # notifikasi dalam aplikasi. Itu bukan kegagalan.
        return result is not None

    # ------------------------------------------------------------------
    # Email
    # ------------------------------------------------------------------
    #
    # Bel dan email sengaja lewat jalur berbeda, dan pembedanya bentuk
    # pesannya: bel adalah **hitung mundur** yang diperbarui tiap hari
    # di tempat yang sama, email adalah **surat** yang menumpuk di kotak
    # masuk. Mengirim surat tiap hari selama tiga puluh hari membuat
    # orang berhenti membacanya jauh sebelum tanggalnya tiba.
    #
    # Keduanya tetap satu baris di bel: `notify()` memakai `object_type`
    # dan `object_id` yang sama persis dengan `_push()` di atas, jadi
    # dedup di `NotificationService.push` menyatukannya alih-alih
    # menghasilkan dua baris untuk kontrak yang sama.

    EVENT_BY_KIND = {
        ReminderKind.PROBATION_END: "hr.probation_end",
        ReminderKind.CONTRACT_END: "hr.contract_end",
        ReminderKind.BIRTHDAY: "hr.birthday",
        ReminderKind.WORK_ANNIVERSARY: "hr.work_anniversary",
    }

    @classmethod
    def _allowed_recipients(cls, policy) -> set[str]:
        """
        Tipe penerima yang diizinkan kebijakan modul.

        `NotificationRule` yang menentukan siapa persisnya; kebijakan ini
        cuma boleh **mempersempit**. Tanpa pembagian itu, dua layar
        menjawab pertanyaan yang sama dan yang menang ditentukan urutan
        kode.
        """
        from apps.notifications.constants import RecipientType

        allowed: set[str] = set()

        if policy.notify_hr:
            allowed |= {
                RecipientType.ROLE,
                RecipientType.USER,
                RecipientType.MANAGER,
                RecipientType.DEPARTMENT_HEAD,
            }

        if policy.notify_employee:
            allowed.add(RecipientType.SUBJECT)

        return allowed

    @classmethod
    def _emit(cls, item: dict, *, policy, milestones: set[int]) -> bool:
        """
        Memicu event notifikasi untuk satu pengingat.

        Mengembalikan True kalau hari ini memang tonggaknya. Di luar
        tonggak tidak ada yang dikirim sama sekali — termasuk belnya,
        yang sudah diurus jalur harian di atas.
        """
        from apps.notifications import notify

        days_left = item["days_left"]

        if days_left not in milestones:
            return False

        event = cls.EVENT_BY_KIND.get(item["kind"])

        if event is None:
            return False

        employee = cls._employee(item["employee_id"])

        notify(
            event=event,
            context={
                "employee_name": item["name"],
                "employee_number": item.get("employee_number") or "",
                "position_name": item.get("position") or "",
                "department_name": item.get("department") or "",
                "location_name": item.get("location") or "",
                "end_date": item["date"].strftime("%d %B %Y"),
                "event_date": item["date"].strftime("%d %B %Y"),
                "days_left": days_left,
                "years": item.get("years") or "",
                "contract_type": item.get("contract_type") or "",
            },
            subject_employee=employee,
            module="hr",
            # Sama persis dengan `_push()` supaya belnya tidak terisi
            # dua baris untuk satu kontrak.
            object_type=f"employee-{item['kind']}",
            object_id=item["employee_id"],
            link=f"/hr/employees/{item['employee_id']}",
            # Tonggaknya ikut jadi kunci: tanpa itu surat H-7 ditolak
            # sebagai duplikat surat H-30, dan pengingat yang justru
            # paling mendesak tidak pernah terkirim.
            dedup_key=(
                f"{event}:{item['employee_id']}:"
                f"{item['date'].isoformat()}:{days_left}"
            ),
            tone="warning" if item["kind"] in SELF_KINDS else "info",
            only_recipient_types=cls._allowed_recipients(policy),
        )

        return True

    @classmethod
    def run(cls, *, dry_run: bool = False) -> dict:
        """
        Jalankan untuk satu tenant. Wajib sudah berada di dalam
        `schema_context()` yang benar.

        Aman diulang berkali-kali sehari: dedup di
        `NotificationService.push` menjaga belnya, dan dedup di
        `NotificationLog` menjaga emailnya.
        """
        policy = EmployeeReminderPolicy.resolve()

        stats = {
            "recipients": 0,
            "written": 0,
            "self_written": 0,
            "skipped_no_account": 0,
            "emails_triggered": 0,
        }

        if policy.notify_hr:
            for user in cls.hr_recipients():
                collected = EmployeeReminderService.collect({"user": user})

                if not collected["items"]:
                    continue

                stats["recipients"] += 1

                for item in collected["items"]:
                    if cls._push(user, item, dry_run=dry_run):
                        stats["written"] += 1

        if policy.notify_employee:
            # Cakupan tidak dipakai di sini, dan itu memang benar: yang
            # dikirim adalah tanggal milik orang itu sendiri, jadi
            # tidak ada yang bisa bocor ke siapa pun.
            everyone = EmployeeReminderService.collect({"user": None})

            for item in everyone["items"]:
                if item["kind"] not in SELF_KINDS:
                    continue

                user = cls._employee_user(item["employee_id"])

                if user is None:
                    stats["skipped_no_account"] += 1
                    continue

                if cls._push(user, item, dry_run=dry_run):
                    stats["self_written"] += 1

        # Email dipicu sekali per pengingat, bukan sekali per penerima —
        # `notify()` yang menyusun daftar penerimanya sendiri. Menyusun
        # terbalik (per penerima, seperti jalur bel di atas) akan
        # mengirim surat yang sama berkali-kali ke orang yang sama
        # begitu ia memegang dua role sekaligus.
        milestones = set(policy.milestones)

        if milestones and not dry_run:
            everyone = EmployeeReminderService.collect({"user": None})

            for item in everyone["items"]:
                if cls._emit(item, policy=policy, milestones=milestones):
                    stats["emails_triggered"] += 1

        logger.info("Pengingat kepegawaian: %s", stats)

        return stats

    @staticmethod
    def _employee(employee_id):
        """Baris pegawai, dipakai resolver penerima untuk cakupan data."""
        from apps.hr.models import Employee

        return (
            Employee.objects
            .select_related("user", "organization")
            .filter(id=employee_id)
            .first()
        )

    @staticmethod
    def _employee_user(employee_id):
        """
        Akun pegawai, kalau ada.

        Pegawai tanpa akun dilewati dan dihitung — bukan diam. Itu
        keadaan yang lazim (pegawai lapangan yang tidak memakai sistem)
        dan pemberitahuannya tetap sampai ke HR, jadi tidak ada yang
        hilang; yang perlu terlihat cuma berapa banyak.
        """
        from apps.hr.models import Employee

        employee = (
            Employee.objects
            .select_related("user")
            .filter(id=employee_id)
            .first()
        )

        return getattr(employee, "user", None)
