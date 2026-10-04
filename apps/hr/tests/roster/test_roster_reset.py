"""
Cakupan `reset_roster_data`.

Pertanyaan yang dijawab berkas ini cuma satu, tapi berdua sisinya:
**apa yang ikut terbuang, dan apa yang harus selamat.** Perintah
penghapusan yang cakupannya melar merusak data yang tidak diminta;
yang cakupannya kurang meninggalkan sisa yang membuat percobaan
berikutnya gagal dengan sebab yang tidak kelihatan.

Dua sisa yang paling mudah tertinggal sudah pernah benar-benar
tertinggal dalam pemakaian nyata, dan keduanya dikunci di sini:
`EmployeeShiftAssignment` yang tidak punya FK ke roster, dan notifikasi
yang tersebar di dua tabel berbeda.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django_tenants.test.cases import TenantTestCase

from apps.administration.models import (
    Company,
    Location,
    Notification,
    RosterPolicy,
    Shift,
)
from apps.hr.models import (
    EmployeeShiftAssignment,
    RosterSetupRequest,
    RotationPeriod,
    SiteRotation,
)
from apps.hr.seeds.roster_reset import run
from apps.notifications.models import NotificationLog
from apps.workflow.models import WorkflowDefinition, WorkflowInstance

User = get_user_model()

# Jenis aksi apa pun; yang diuji statusnya, bukan isinya.
ACTION_TYPE = "transfer"


class RosterResetTestCase(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "roster-reset"
        tenant.name = "Roster Reset"

    _seq = 0

    def tag(self):
        type(self)._seq += 1

        return f"RR{type(self)._seq:04d}"

    def setUp(self):
        super().setUp()

        tag = self.tag()

        self.user = User.objects.create_user(
            username=f"reset.{tag.lower()}",
            email=f"reset.{tag.lower()}@example.test",
            password="reset-pass-1",
        )

        self.policy = RosterPolicy.objects.create(
            code=f"POL-{tag}",
            name=f"Policy {tag}",
        )

        self.shift = Shift.objects.create(
            code=f"SH-{tag}",
            name=f"Shift {tag}",
            start_time="07:00",
            end_time="15:00",
        )

        # `Location.company` non-null tapi `blank=True`, jadi tidak
        # muncul sebagai "wajib" di introspeksi form — hanya database
        # yang menolaknya.
        self.company = Company.objects.create(
            code=f"CMP-{tag}",
            name=f"Perusahaan {tag}",
        )

        self.location = Location.objects.create(
            company=self.company,
            code=f"LOC-{tag}",
            name=f"Lokasi {tag}",
        )

    # ------------------------------------------------------------------
    # Bahan uji
    # ------------------------------------------------------------------

    def make_workflow(self, *, document_type, status="approved"):
        tag = self.tag()

        definition = WorkflowDefinition.objects.create(
            code=f"WF-{tag}",
            name=f"Alur {tag}",
            module="hr",
            document_type=document_type,
        )

        return WorkflowInstance.objects.create(
            definition=definition,
            module="hr",
            document_type=document_type,
            document_number=f"DOC-{tag}",
            object_id=1,
            status=status,
        )

    def make_notifications(self, object_type):
        Notification.objects.create(
            user=self.user,
            title=f"Notifikasi {object_type}",
            object_type=object_type,
        )
        NotificationLog.objects.create(
            event="workflow.approved",
            channel="in_app",
            object_type=object_type,
        )

    def make_roster(self):
        from apps.hr.models import Employee

        employee = Employee.objects.create(
            employee_number=f"RST{self.tag()}",
            first_name="Uji",
            last_name="Reset",
        )

        rotation = SiteRotation.objects.create(
            employee=employee,
            roster_policy=self.policy,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 12, 31),
        )

        RotationPeriod.objects.create(
            rotation=rotation,
            employee=employee,
            sequence=1,
            period_type="work",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 7),
        )

        EmployeeShiftAssignment.objects.create(
            employee=employee,
            shift=self.shift,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 7),
            layer="baseline",
        )

        return rotation


class RosterScopeTests(RosterResetTestCase):
    """Bawaan: hanya milik roster."""

    def test_roster_rows_are_removed(self):
        self.make_roster()

        run(log=lambda *a: None)

        self.assertEqual(SiteRotation.objects.count(), 0)
        self.assertEqual(RotationPeriod.objects.count(), 0)

    def test_shift_assignments_are_removed_although_nothing_cascades(self):
        """
        `EmployeeShiftAssignment` tidak punya FK ke roster sama sekali.
        Kalau perintahnya mengandalkan cascade, baris ini tertinggal dan
        Shift Calendar tetap menampilkan shift di tanggal yang rosternya
        sudah tidak ada.
        """
        self.make_roster()

        run(log=lambda *a: None)

        self.assertEqual(EmployeeShiftAssignment.objects.count(), 0)

    def test_other_modules_keep_their_workflow(self):
        keep = self.make_workflow(document_type="leave_request")
        drop = self.make_workflow(document_type="roster_setup")

        run(log=lambda *a: None)

        self.assertTrue(
            WorkflowInstance.objects.filter(pk=keep.pk).exists(),
            "pengajuan cuti ikut terbuang padahal cakupannya roster",
        )
        self.assertFalse(
            WorkflowInstance.objects.filter(pk=drop.pk).exists(),
        )

    def test_other_modules_keep_their_notifications(self):
        self.make_notifications("hr-leave_request")
        self.make_notifications("hr-roster_setup")

        run(log=lambda *a: None)

        self.assertEqual(
            Notification.objects.filter(
                object_type="hr-leave_request",
            ).count(),
            1,
        )
        self.assertEqual(
            Notification.objects.filter(
                object_type="hr-roster_setup",
            ).count(),
            0,
        )

    def test_both_notification_tables_are_cleared(self):
        """
        Notifikasi hidup di dua tabel: satu mengisi bel, satu mencatat
        pengiriman. Membersihkan satu saja membuat bel tetap terisi
        padahal log-nya sudah kosong.
        """
        self.make_notifications("hr-roster_setup")

        run(log=lambda *a: None)

        self.assertEqual(
            Notification.objects.filter(
                object_type="hr-roster_setup",
            ).count(),
            0,
        )
        self.assertEqual(
            NotificationLog.objects.filter(
                object_type="hr-roster_setup",
            ).count(),
            0,
        )

    def test_configuration_survives(self):
        """
        Yang dibutuhkan untuk mengulang entry tidak boleh ikut hilang —
        kalau ikut, "reset supaya bisa dicoba lagi" justru membuat
        percobaan berikutnya mustahil.
        """
        self.make_roster()

        run(log=lambda *a: None)

        self.assertTrue(
            RosterPolicy.objects.filter(pk=self.policy.pk).exists(),
        )
        self.assertTrue(Shift.objects.filter(pk=self.shift.pk).exists())


class AllScopeTests(RosterResetTestCase):
    """`--all`: pengajuan dan notifikasi seluruh modul."""

    def test_every_module_workflow_is_removed(self):
        self.make_workflow(document_type="leave_request")
        self.make_workflow(document_type="employee_action")
        self.make_workflow(document_type="roster_setup")

        run(log=lambda *a: None, scope="all")

        self.assertEqual(WorkflowInstance.objects.count(), 0)

    def test_every_module_notification_is_removed(self):
        self.make_notifications("hr-leave_request")
        self.make_notifications("employee-birthday")

        run(log=lambda *a: None, scope="all")

        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(NotificationLog.objects.count(), 0)


class KeepNotificationsTests(RosterResetTestCase):
    def test_notifications_survive_when_asked(self):
        self.make_roster()
        self.make_notifications("hr-roster_setup")

        run(log=lambda *a: None, keep_notifications=True)

        self.assertEqual(SiteRotation.objects.count(), 0)
        self.assertEqual(
            Notification.objects.filter(
                object_type="hr-roster_setup",
            ).count(),
            1,
        )


class StrandedDocumentTests(RosterResetTestCase):
    """
    Dokumen yang **selamat** dari reset tapi kehilangan alurnya.

    Dokumen roster tidak masuk hitungan: ia ikut terhapus beberapa
    langkah kemudian, jadi tidak ada yang menggantung. Yang menggantung
    adalah dokumen modul lain saat `--all` — statusnya tinggal
    `submitted` sementara jalur persetujuannya sudah hilang, tidak bisa
    disetujui dan tidak bisa diteruskan.
    """

    def make_action(self, status):
        from apps.hr.models import Employee, EmployeeAction

        employee = Employee.objects.create(
            employee_number=f"ACT{self.tag()}",
            first_name="Uji",
            last_name="Aksi",
        )

        return EmployeeAction.objects.create(
            document_number=f"EAC-{self.tag()}",
            employee=employee,
            action_type=ACTION_TYPE,
            effective_date=date(2026, 9, 1),
            status=status,
        )

    def attach(self, document, *, document_type, status):
        instance = self.make_workflow(
            document_type=document_type,
            status=status,
        )
        instance.object_id = document.pk
        instance.save(update_fields=["object_id"])

        return instance

    def test_an_unfinished_document_is_returned_to_draft(self):
        document = self.make_action("submitted")

        self.attach(
            document,
            document_type="employee_action",
            status="pending",
        )

        counts = run(log=lambda *a: None, scope="all")

        document.refresh_from_db()

        self.assertEqual(document.status, "draft")
        self.assertEqual(counts["dokumen dikembalikan"], 1)

    def test_a_finished_document_is_left_alone(self):
        document = self.make_action("applied")

        self.attach(
            document,
            document_type="employee_action",
            status="approved",
        )

        counts = run(log=lambda *a: None, scope="all")

        document.refresh_from_db()

        self.assertEqual(document.status, "applied")
        self.assertEqual(counts["dokumen dikembalikan"], 0)

    def test_the_roster_scope_leaves_other_modules_untouched(self):
        """
        Pada cakupan roster, pengajuan modul lain tidak dibuang — jadi
        dokumennya juga tidak boleh dipulangkan ke draft.
        """
        document = self.make_action("submitted")

        self.attach(
            document,
            document_type="employee_action",
            status="pending",
        )

        counts = run(log=lambda *a: None)

        document.refresh_from_db()

        self.assertEqual(document.status, "submitted")
        self.assertEqual(counts["dokumen dikembalikan"], 0)
