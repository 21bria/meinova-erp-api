"""
Menindaklanjuti kewajiban cuti yang lahir dari presensi.

`AttendancePolicyResolver.compute()` cuma **menandai**: ia menulis
`leave_required_days` dan sebabnya, lalu berhenti. Selama tidak ada
yang menindaklanjutinya, penanda itu tersimpan di kolom yang tidak
dibuka siapa pun sampai ada yang kebetulan membuka layar Attendance.
Berkas ini yang menutupnya, dan bentuknya **dua tombol, bukan otomatis**.

Kenapa jangan pernah menerbitkan cutinya otomatis
-------------------------------------------------
Tiga alasan, dan ketiganya sudah jadi prinsip di modul lain:

1. **Saldo tidak pernah berkurang tanpa persetujuan.** Berlaku di
   seluruh codebase ini, termasuk di jalur Travel Request yang baru
   menerbitkan catatan cuti setelah alurnya selesai.
2. **Kasus yang punya alasan harus bisa dibebaskan tanpa menghapus
   catatan presensinya.** Ban bocor, kapal digeser, izin atasan yang
   tidak sempat ditulis. Menghapus baris presensi untuk membatalkan
   potongan berarti membuang fakta jam tapnya.
3. **Satu import fingerprint bisa menerbitkan ratusan dokumen
   sekaligus**, dan yang salah tidak bisa ditarik satu per satu.

Kenapa bukan engine workflow
----------------------------
Engine `apps.workflow` membangun seluruh baris keputusan di depan saat
submit, dan dirancang untuk **dokumen** — satu Travel Request, satu
Employee Action. Satu import fingerprint melahirkan ratusan pengecualian
dalam satu tarikan; satu `WorkflowInstance` per baris presensi akan
membanjiri kotak masuk yang sama yang dipakai menyetujui cuti dan
perjalanan dinas, dan yang penting tenggelam di antara yang rutin.

Jadi peninjauannya ringan: dua kolom keputusan di baris presensi itu
sendiri, penerimanya diambil dari `manager_of()` yang **sama** dengan
yang dipakai engine approval — bukan field supervisor baru.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.hr.models import EmployeeAttendance, LeaveStatus


logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")


class AttendanceObligationService:
    """Keputusan atas satu baris presensi yang menandai kewajiban cuti."""

    # ------------------------------------------------------------------
    # Siapa yang boleh memutuskan
    # ------------------------------------------------------------------

    @staticmethod
    def supervisor_of(employee):
        """
        Atasan langsung, lewat `OrganizationAssignment.reports_to`.

        Dibaca dari resolver engine approval, **bukan disalin**: dua
        salinan aturan "siapa atasan siapa" akan membuat orang yang
        meninjau presensi berbeda dari orang yang menyetujui cutinya —
        dan selisih seperti itu tidak berbunyi.
        """
        from apps.workflow.resolver import manager_of

        return manager_of(employee)

    @classmethod
    def assert_can_review(cls, *, instance: EmployeeAttendance, user) -> None:
        """
        Yang boleh: atasan langsung pegawainya, HR yang memang punya
        izin mengubah presensi, dan superuser.

        Superuser diperiksa **paling akhir** supaya yang kebetulan juga
        atasan tetap tercatat sebagai atasan — bukan sebagai orang yang
        melewati aturannya.
        """
        if user is None or not getattr(user, "is_authenticated", False):
            raise PermissionDenied(
                "Perlu masuk untuk meninjau kewajiban cuti.",
            )

        supervisor = cls.supervisor_of(instance.employee)

        # `manager_of()` mengembalikan **Employee**, sedangkan yang
        # login **User** — dua ruang id yang berbeda. Membandingkan
        # `supervisor.pk == user.pk` karena itu salah di dua arah
        # sekaligus, dan dua-duanya diam:
        #
        # * atasan sungguhan **ditolak**, jadi tombol Waive di layar
        #   Attendance cuma bisa dipakai HR dan superuser — persis
        #   orang yang paling tidak tahu kenapa seseorang terlambat;
        # * siapa pun yang id User-nya kebetulan sama dengan id
        #   Employee sang atasan justru **lolos**. Di tenant kecil
        #   tabrakan id seperti itu bukan hal langka.
        #
        # Yang benar: akun yang tertaut ke Employee atasan itu.
        # Atasan yang belum punya akun tidak lolos lewat cabang ini —
        # dan memang tidak bisa, karena ia tidak bisa login.
        if (
            supervisor is not None
            and supervisor.user_id
            and supervisor.user_id == user.pk
        ):
            return

        if user.has_perm("hr.change_employeeattendance"):
            return

        if getattr(user, "is_superuser", False):
            return

        raise PermissionDenied(
            "Hanya atasan langsung pegawai ini atau HR yang boleh "
            "memutuskan kewajiban cutinya.",
        )

    # ------------------------------------------------------------------
    # Keputusan
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def waive(
        cls,
        *,
        instance: EmployeeAttendance,
        reason: str,
        user=None,
    ) -> EmployeeAttendance:
        """
        Membebaskan: hari ini tidak perlu mengajukan cuti.

        `leave_required_days` **tidak** disentuh — ia tetap menyimpan
        angka menurut aturan, dan itu faktanya. Kalau pembebasan ditulis
        ke kolom yang sama, ia tidak bisa dibedakan lagi dari aturan
        yang memang tidak menyala, dan pertanyaan "kenapa orang ini
        tidak dipotong" kehilangan jawabannya.
        """
        cls.assert_can_review(instance=instance, user=user)

        reason = (reason or "").strip()

        if not reason:
            raise ValidationError(
                {
                    "reason": (
                        "Alasan pembebasan wajib diisi. Pembebasan "
                        "tanpa alasan tertulis membuat aturan ini "
                        "kehilangan wibawanya dalam tiga bulan."
                    ),
                },
            )

        instance.leave_required_waived = True
        instance.leave_required_waiver_reason = reason
        instance.review_decision = "valid"
        instance.review_notes = reason
        instance.reviewed_at = timezone.now()
        instance.reviewed_by = user

        instance.full_clean()

        instance.save(
            update_fields=[
                "leave_required_waived",
                "leave_required_waiver_reason",
                "review_decision",
                "review_notes",
                "reviewed_at",
                "reviewed_by",
                "updated_at",
            ],
        )

        return instance

    @classmethod
    @transaction.atomic
    def require_leave(
        cls,
        *,
        instance: EmployeeAttendance,
        notes: str = "",
        days: Decimal | None = None,
        user=None,
    ) -> EmployeeAttendance:
        """
        Atasan menilai pengecualiannya tidak sah: pegawainya harus
        mengajukan cuti.

        Yang berubah cuma keputusannya. Dokumen cutinya **tidak**
        diterbitkan di sini — pegawainya yang mengajukan lewat modul
        Cuti seperti biasa, dan itu yang membuat alur persetujuannya
        tetap satu. `issue_leave()` ada untuk HR yang memang mencatatkan
        cutinya sendiri.
        """
        cls.assert_can_review(instance=instance, user=user)

        if instance.leave_required_waived:
            # Membebaskan lalu menagih tanpa mencabut pembebasannya akan
            # meninggalkan baris yang dua-duanya benar sekaligus.
            instance.leave_required_waived = False
            instance.leave_required_waiver_reason = ""

        if days is not None:
            instance.leave_required_override = Decimal(days)

        instance.review_decision = "require_leave"
        instance.review_notes = (notes or "").strip()
        instance.reviewed_at = timezone.now()
        instance.reviewed_by = user

        instance.full_clean()

        instance.save(
            update_fields=[
                "leave_required_waived",
                "leave_required_waiver_reason",
                "leave_required_override",
                "review_decision",
                "review_notes",
                "reviewed_at",
                "reviewed_by",
                "updated_at",
            ],
        )

        cls.notify_leave_required(instance)

        return instance

    @classmethod
    @transaction.atomic
    def issue_leave(
        cls,
        *,
        instance: EmployeeAttendance,
        leave_type=None,
        user=None,
    ):
        """
        Menerbitkan dokumen cutinya sebagai DRAFT, tertaut ke baris ini.

        Lewat `EmployeeLeaveService`, **bukan** `objects.create`:
        service itu yang menghitung hari kerjanya, memberi nomor
        dokumen, dan menjumlahkan ulang `LeaveBalance`. Menulis
        langsung ke model berarti kartu cutinya tidak ikut bergerak dan
        selisihnya baru ketahuan berbulan-bulan kemudian.

        Statusnya DRAFT, bukan APPROVED: yang menerbitkan bukan yang
        berhak menyetujui, dan saldo tidak pernah berkurang tanpa
        persetujuan.
        """
        from apps.hr.api.attendance.policy import AttendancePolicyResolver
        from apps.hr.api.leave.services import EmployeeLeaveService

        cls.assert_can_review(instance=instance, user=user)

        if instance.leave is not None and not instance.leave.is_deleted:
            raise ValidationError(
                {
                    "leave": (
                        f"Sudah ada dokumen cuti "
                        f"({instance.leave.document_number or instance.leave.pk}) "
                        f"untuk hari ini."
                    ),
                },
            )

        days = instance.leave_required_effective

        if days is None or days <= ZERO:
            raise ValidationError(
                {
                    "leave": (
                        "Baris ini tidak menandai kewajiban cuti apa pun."
                    ),
                },
            )

        if leave_type is None:
            policy = AttendancePolicyResolver.match(instance.employee)
            leave_type = getattr(policy, "leave_type", None)

        if leave_type is None:
            # Ditolak, bukan ditebak. Menerbitkan cuti dengan jenis yang
            # ditebak berarti memotong saldo yang salah, dan itu baru
            # ketahuan saat orangnya mengajukan cuti tahunan lalu
            # ditolak karena saldonya habis.
            raise ValidationError(
                {
                    "leave_type": (
                        "Attendance Policy yang berlaku belum menyebut "
                        "jenis cuti yang dipotong. Isi dulu di layar "
                        "Attendance Policy."
                    ),
                },
            )

        # `leave_deduction_days` menyimpan dua desimal, `total_days`
        # cuma satu. Tanpa pembulatan di sini, potongan 0,25 hari
        # menjatuhkan penyimpanan dengan pesan tentang tempat desimal —
        # jauh dari layar tempat angkanya diketik, dan tidak menyebut
        # policy mana yang menyebabkannya.
        #
        # Dibulatkan ke atas pada setengahnya: yang membulatkan ke bawah
        # menghasilkan potongan yang lebih kecil daripada yang tertulis
        # di aturan, dan selisih itu selalu menguntungkan satu pihak.
        rounded = days.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

        leave = EmployeeLeaveService.create(
            data={
                "employee": instance.employee,
                "leave_type": leave_type,
                "start_date": instance.work_date,
                "end_date": instance.work_date,
                "total_days": rounded,
                "status": LeaveStatus.DRAFT,
                "notes": (
                    f"Diterbitkan dari catatan presensi "
                    f"{instance.work_date} "
                    f"({instance.get_leave_required_reason_display() or 'kewajiban cuti'})."
                ),
            },
            user=user,
        )

        instance.leave = leave
        instance.review_decision = "require_leave"
        instance.reviewed_at = instance.reviewed_at or timezone.now()
        instance.reviewed_by = instance.reviewed_by or user

        instance.save(
            update_fields=[
                "leave",
                "review_decision",
                "reviewed_at",
                "reviewed_by",
                "updated_at",
            ],
        )

        return leave

    # ------------------------------------------------------------------
    # Pemberitahuan
    # ------------------------------------------------------------------

    @staticmethod
    def _context(instance: EmployeeAttendance) -> dict[str, Any]:
        employee = instance.employee

        return {
            "employee_name": employee.full_name,
            "employee_number": employee.employee_number,
            "work_date": instance.work_date.strftime("%d %B %Y"),
            "late_minutes": instance.late_minutes or 0,
            "early_leave_minutes": instance.early_leave_minutes or 0,
            "reason_label": (
                instance.get_leave_required_reason_display() or "-"
            ),
            "leave_days": str(instance.leave_required_effective),
        }

    @classmethod
    def notify_exception(cls, instance: EmployeeAttendance) -> bool:
        """
        Mengabarkan pengecualian yang baru terdeteksi.

        Penerimanya diatur `NotificationRule` seperti event lain;
        bawaannya pegawainya sendiri + atasan langsung. Saklar di
        `AttendancePolicy` yang menentukan apakah dikirim sama sekali —
        tenant yang tidak mau membanjiri kotak masuk mematikannya di
        satu tempat, bukan mencabut aturan penerimanya.
        """
        from apps.hr.api.attendance.policy import AttendancePolicyResolver
        from apps.notifications import notify

        policy = AttendancePolicyResolver.match(instance.employee)

        if policy is not None and not (
            policy.notify_employee
            or policy.notify_supervisor
            or policy.notify_hr
        ):
            return False

        types = []

        if policy is None or policy.notify_employee:
            types.append("subject")

        if policy is None or policy.notify_supervisor:
            types.append("manager")

        if policy is not None and policy.notify_hr:
            types.append("role")

        notify(
            event="hr.attendance_exception",
            context=cls._context(instance),
            subject_employee=instance.employee,
            module="hr",
            object_type="attendance-exception",
            object_id=instance.pk,
            link="/hr/attendance",
            # Satu baris presensi = satu surat, walau perhitungan
            # ulangnya dijalankan berkali-kali. Tanpa ini,
            # `recalculate_attendance` yang dijalankan tiap kali policy
            # disunting akan mengirim ulang seluruh pengecualian bulan
            # itu.
            dedup_key=f"hr.attendance_exception:{instance.pk}",
            # Mempersempit, tidak pernah memperluas: kalau modul boleh
            # menambah penerima, layar Notification Rules berhenti
            # menjawab "siapa saja yang menerima ini".
            only_recipient_types=types,
            tone="warning",
        )

        return True

    @classmethod
    def notify_leave_required(cls, instance: EmployeeAttendance) -> None:
        from apps.notifications import notify

        notify(
            event="hr.attendance_leave_required",
            context={
                **cls._context(instance),
                "review_notes": instance.review_notes or "-",
            },
            subject_employee=instance.employee,
            module="hr",
            object_type="attendance-leave-required",
            object_id=instance.pk,
            link="/hr/leave",
            # Keputusannya boleh berubah — atasan yang meninjau ulang
            # dan tetap menagih cuti mengirim surat lagi. Waktunya ikut
            # di kunci supaya yang kedua tidak ditolak sebagai duplikat
            # yang pertama.
            dedup_key=(
                f"hr.attendance_leave_required:{instance.pk}:"
                f"{instance.reviewed_at.date() if instance.reviewed_at else ''}"
            ),
            tone="warning",
        )
