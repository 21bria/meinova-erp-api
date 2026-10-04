"""
Setup roster massal: Site → Section → Employees → Preview → Approval.

Satu dokumen, satu pengajuan, **satu item di kotak masuk approver**.
Tiga puluh pegawai tidak boleh jadi tiga puluh tombol Approve yang
isinya sama.

Dua aturan yang lahir dari bentuk engine, bukan dari selera
--------------------------------------------------------------
`WorkflowService.submit()` menerima `scope`, tapi `scope` hanya
mengatur pencocokan `WorkflowDefinition` dan mengisi kolom organisasi
instance. Penyusunan approver tetap berangkat dari satu `employee` —
tipe `manager`, `department_head`, dan `position` semuanya membaca
`OrganizationAssignment` miliknya.

Dokumen batch tidak punya satu pegawai subjek. Konsekuensinya:

1. **Satu batch = satu Site.** Kalau bercampur, cakupan approver tidak
   bisa ditentukan, dan kebocorannya diam: dokumennya tetap tampil,
   cuma di meja yang salah.
2. **Step per-pegawai boleh dipakai, tapi hanya kalau seluruh baris
   menghasilkan approver yang sama.** Aturan lamanya "alurnya hanya
   boleh memakai step Role/User", dan itu membuang justru meja yang
   paling diminta: persetujuan **atasan langsung** pegawai yang
   dijadwalkan. Yang menggantikannya bukan pelonggaran — dokumen yang
   atasannya berbeda-beda **ditolak dengan menyebut siapa membawahi
   siapa**, supaya dipecah per atasan. Yang tidak boleh terjadi adalah
   salah satu atasan dipilih diam-diam dan yang lain tidak pernah tahu
   jadwal timnya berubah.

Sampel organisasi untuk cakupan role diambil dari baris ber-nomor
pegawai terkecil — sah karena aturan (1), dan deterministik supaya dua
submit yang sama menghasilkan approver yang sama. Untuk step
per-pegawai, aturan (2) yang membuat sampel itu **terbukti** mewakili
seluruh batch, bukan sekadar deterministik.
"""

from __future__ import annotations

import logging

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.administration.api.numbering.services.numbering_service import (
    DocumentNumberService,
)
from apps.core.services.master import BaseMasterService
from apps.hr.applicability import HRFeature, filter_employees

from apps.hr.api.roster.services import (
    RosterGenerationService,
    RosterValidator,
)
from apps.hr.models import (
    Employee,
    RosterSetupLine,
    RosterSetupLineStatus,
    RosterSetupRequest,
    RosterSetupStatus,
    SiteRotationStatus,
)


logger = logging.getLogger(__name__)


MODULE = "hr"
DOCUMENT_TYPE = "roster_setup"

# Tiga puluh baris × 26 segmen setahun ≈ 780 baris dalam satu transaksi;
# dua ratus baris ≈ 5.200 dan itu batas yang masih wajar untuk satu
# commit. Di atas itu batch dipecah per Section, dan itu memang
# pembagian kerja yang benar.
MAX_SETUP_LINES = 200


# Tipe approver yang berangkat dari **satu** pegawai subjek. Dokumen
# batch punya banyak, jadi step bertipe ini diperiksa dulu: boleh
# dipakai kalau seluruh baris jatuh ke orang yang sama, ditolak dengan
# menyebut kelompoknya kalau tidak. Tipe `role` dan `user` tidak ikut —
# keduanya memang tidak membaca pegawai subjek.
PER_EMPLOYEE_APPROVER_TYPES = {"manager", "department_head", "position"}


class RosterSetupService(BaseMasterService):
    model = RosterSetupRequest

    # ------------------------------------------------------------------
    # Penyiapan
    # ------------------------------------------------------------------

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.apply_scope_defaults(data=data, user=user)

        location = data.get("location")

        if location is not None and not data.get("company"):
            data["company"] = location.company

        cls.assert_within_scope(data=data, user=user)

        if not data.get("as_of_date"):
            data["as_of_date"] = timezone.localdate()

        if not data.get("document_number"):
            data["document_number"] = DocumentNumberService.next(
                module=MODULE,
                document_type=DOCUMENT_TYPE,
                company=data.get("company"),
            )

        return data

    # Peta cakupan untuk memeriksa satu baris Location. Sengaja memakai
    # mesin yang sama dengan penyaringan daftar (`DataScopeService`)
    # alih-alih menyalin semantik AND/OR-nya ke sini — dua salinan
    # aturan cakupan cepat atau lambat berbeda, dan yang satu akan
    # membuka apa yang ditutup satunya.
    LOCATION_SCOPE = {
        "company": "company_id",
        "branch": "branch_id",
        "location": "id",
    }

    # Penyaring di bawah site ikut dijaga, dan itu yang membedakan
    # Admin Section dari Admin Department: keduanya duduk di site yang
    # sama, izin modelnya sama persis, dan yang memisahkan mereka
    # **baris siapa** — jadi kalau Section tidak diperiksa di sini,
    # Admin Section bisa mengetik section sebelah ke dalam dokumennya.
    #
    # Jenis yang tidak ada di peta dilewati `DataScopeService.filter`,
    # jadi role bercakupan Section tetap boleh menyebut Department
    # induknya di kepala dokumen — yang menentukan siapa yang benar
    # benar masuk tetap `eligible_employees()`.
    DEPARTMENT_SCOPE = {
        "company": "company_id",
        "branch": "branch_id",
        "location": "location_id",
        "division": "division_id",
        "department": "id",
    }

    SECTION_SCOPE = {
        "company": "company_id",
        "branch": "branch_id",
        "location": "location_id",
        "division": "division_id",
        "department": "department_id",
        "section": "id",
    }

    @staticmethod
    def apply_scope_defaults(*, data: dict[str, Any], user=None) -> None:
        """
        Isi Company/Site/Department/Section dari cakupan pembuatnya
        kalau tidak disebut.

        Bukan kenyamanan: admin yang cuma boleh melihat satu site,
        kalau membuat dokumen tanpa mengisi Site, menyimpan baris yang
        **seketika hilang dari layarnya sendiri** — tersimpan (201),
        lalu 404 saat dibuka lagi. Dari kursinya itu terbaca seperti
        penyimpanan yang gagal, tanpa satu pesan pun yang menjelaskan.

        Department dan Section ikut, dan justru merekalah yang paling
        sering kena: cakupan Admin Section memang `section`, jadi
        dokumen yang Section-nya dibiarkan kosong lolos `data_scope`
        viewset (`Q(section=…)` tidak pernah cocok dengan `NULL`) dan
        hilang dari layar orang yang baru saja membuatnya.

        Yang tanpa batasan tidak diisikan apa-apa: mereka memang boleh
        membuat dokumen untuk site mana pun, dan mengisikan lokasinya
        sendiri justru menaruh dokumen site di kantor pusat.
        """
        from apps.accounts.scoping import DataScopeService
        from apps.administration.models import (
            Company,
            Department,
            Location,
            Section,
        )

        implied = DataScopeService.implied_values(user)

        if not implied:
            return

        for field, model in (
            ("location", Location),
            ("company", Company),
            ("department", Department),
            ("section", Section),
        ):
            if data.get(field) or not implied.get(field):
                continue

            data[field] = model.objects.filter(
                pk=implied[field],
                is_deleted=False,
            ).first()

    @classmethod
    def assert_within_scope(cls, *, data: dict[str, Any], user=None) -> None:
        """
        Tolak Site / Department / Section di luar cakupan pembuatnya.

        Mengunci dropdown di form **bukan** penjagaan — endpoint-nya
        tetap bisa ditembak langsung, dan `filter_queryset()` cuma
        menjaga baca dan ubah, tidak menjaga create. Tanpa ini admin
        Gebe bisa membuat dokumen untuk Jakarta HO lewat satu request
        yang isinya diketik tangan.
        """
        from apps.accounts.scoping import DataScopeService
        from apps.administration.models import Department, Location, Section

        if user is None or not getattr(user, "is_authenticated", False):
            return

        if user.is_superuser:
            return

        # **TERBLOKIR, disengaja: tanpa `permission`.**
        #
        # Yang diperiksa di sini bukan "boleh membaca Location", tapi
        # "boleh menyusun roster untuk lokasi ini" — dan tidak ada izin
        # model yang menyatakan itu. Memakai `administration.view_location`
        # akan menjawab pertanyaan yang berbeda dari yang ditanyakan,
        # dan kebetulan jawabannya sering sama bukan alasan yang cukup.
        #
        # Akibatnya jalur ini masih memakai cakupan gabungan seluruh
        # role. Lihat catatan Stage 3B.2 — butuh gagasan "otoritas
        # wilayah kerja" yang belum ada.
        scope = DataScopeService.for_user(user)

        if scope.unrestricted:
            return

        targets = [
            ("location", data.get("location"), Location, cls.LOCATION_SCOPE),
            (
                "department",
                data.get("department"),
                Department,
                cls.DEPARTMENT_SCOPE,
            ),
            ("section", data.get("section"), Section, cls.SECTION_SCOPE),
        ]

        labels = {
            "location": "Site",
            "department": "Department",
            "section": "Section",
        }

        for field, value, model, mapping in targets:
            if value is None:
                continue

            allowed = DataScopeService.filter(
                model.objects.filter(pk=value.pk),
                mapping,
                user,
            ).exists()

            if allowed:
                continue

            raise ValidationError(
                {
                    field: (
                        f"{labels[field]} {value} di luar cakupan data "
                        "Anda. Hubungi administrator kalau unit itu "
                        "memang tanggung jawab Anda."
                    ),
                },
            )

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.assert_editable(instance)

        # Kepala dokumen boleh dipindah selagi Draft, jadi penjagaan
        # cakupannya harus ikut jalan di sini juga — kalau tidak, satu
        # PATCH memindahkan dokumen ke site yang tidak boleh dilihat
        # pembuatnya, dan barisnya hilang dari layarnya sendiri.
        cls.assert_within_scope(
            data={
                "location": data.get("location", instance.location),
                "department": data.get("department", instance.department),
                "section": data.get("section", instance.section),
            },
            user=user,
        )

        return data

    @staticmethod
    def assert_editable(instance: RosterSetupRequest) -> None:
        """
        Dokumen yang sedang menunggu persetujuan atau sudah disetujui
        tidak boleh disunting bebas — yang sudah ditandatangani harus
        tetap menunjuk isi yang ditandatangani. Tarik dulu
        pengajuannya, dan itu tindakan yang terlihat.
        """
        if instance.is_editable:
            return

        raise ValidationError(
            {
                "status": (
                    f"Dokumen berstatus "
                    f"{instance.get_status_display()} tidak bisa "
                    "disunting. Tarik dulu pengajuannya."
                ),
            },
        )

    # ------------------------------------------------------------------
    # Kandidat
    # ------------------------------------------------------------------

    @staticmethod
    def candidates(*, location, department=None, section=None, queryset=None):
        """
        Pegawai yang layak disetup di site ini.

        Yang dibuang: yang sudah punya rencana berjalan, dan yang sudah
        berhenti. Yang **tidak** dibuang: yang belum punya Roster
        Policy — justru merekalah yang perlu disetup, dan menyaringnya
        di sini membuat layar bulk selalu kosong untuk tenant baru.

        `queryset` dioper viewset supaya cakupan data ikut
        berlaku; tanpa itu admin site melihat nama pegawai site lain di
        layar setup.
        """
        from apps.hr.models import SiteRotation, ROSTER_LIVE_STATUSES

        base = queryset if queryset is not None else Employee.objects.all()

        base = (
            base
            .filter(
                is_active=True,
                is_deleted=False,
                organization__location=location,
                organization__is_deleted=False,
            )
            .select_related(
                "organization",
                "organization__department",
                "organization__section",
                "organization__position",
                "organization__reports_to",
                "employment",
                "employment__employee_group",
                "employment__roster_policy",
                "employment__point_of_hire",
            )
        )

        # Group yang Roster-nya dimatikan tidak pernah jadi kandidat.
        # Ini penyaring **kelayakan**, sejajar dengan dua di atas (sudah
        # punya rencana, sudah berhenti) — bukan cakupan data, yang
        # tetap dipegang `queryset` kiriman viewset.
        base = filter_employees(base, HRFeature.ROSTER)

        # Berjenjang, dan dua-duanya di-AND kalau sama-sama diisi.
        # Section yang tidak berada di bawah Department yang dipilih
        # sudah ditolak `clean()`, jadi kombinasi itu tidak pernah
        # sampai ke sini dalam keadaan bertentangan.
        if department is not None:
            base = base.filter(organization__department=department)

        if section is not None:
            base = base.filter(organization__section=section)

        busy = (
            SiteRotation.objects
            .filter(
                is_deleted=False,
                effective_to__isnull=True,
                status__in=ROSTER_LIVE_STATUSES,
            )
            .values_list("employee_id", flat=True)
        )

        return (
            base
            .exclude(pk__in=busy)
            .exclude(employment__termination_date__isnull=False)
            .order_by("employee_number")
        )

    # ------------------------------------------------------------------
    # Kelayakan satu pegawai
    # ------------------------------------------------------------------

    # Peta cakupan daftar pegawai. **Satu salinan** yang dipakai baik
    # oleh dropdown kandidat maupun oleh penjagaan penambahan baris —
    # dua salinan cepat atau lambat berbeda, dan yang menerima id
    # kiriman klien-lah yang akan melebar tanpa yang menyusun dropdown
    # ikut menyempit.
    EMPLOYEE_SCOPE = {
        "company": "organization__company",
        "branch": "organization__branch",
        "location": "organization__location",
        "division": "organization__division",
        "department": "organization__department",
        "section": "organization__section",
        "own": "user_id",
    }

    @classmethod
    def scoped_employees(cls, user=None):
        """Pegawai aktif yang boleh dilihat `user`, tanpa penyaring lain."""
        from apps.accounts.scoping import DataScopeService

        from apps.accounts.permissions import view_permission_for

        return DataScopeService.filter(
            Employee.objects.filter(is_active=True, is_deleted=False),
            cls.EMPLOYEE_SCOPE,
            user,
            required_permission=view_permission_for(Employee),
        )

    @classmethod
    def eligible_employees(cls, *, request, user=None):
        """
        Pegawai yang boleh masuk dokumen ini, dari kursi `user`.

        Gabungan dua penyaring yang selama ini hidup terpisah:
        kelayakan dokumen (site/department/section, Feature
        Applicability, belum punya rencana berjalan) dan cakupan data
        pembuatnya. Dipakai **dua-duanya** oleh dropdown kandidat dan
        oleh penjagaan penambahan baris, jadi apa yang ditawarkan layar
        dan apa yang diterima API tidak bisa berbeda.
        """
        return cls.candidates(
            location=request.location,
            department=request.department,
            section=request.section,
            queryset=cls.scoped_employees(user),
        )

    @classmethod
    def assert_employee_allowed(
        cls,
        *,
        request: RosterSetupRequest,
        employee,
        user=None,
    ) -> None:
        """
        Menolak pegawai yang tidak boleh masuk dokumen ini.

        Menyaring dropdown **bukan** penjagaan: `add-employees` dan
        `POST /roster-setup-lines/` sama-sama menerima id yang diketik
        tangan, dan tanpa ini pegawai kantor pusat, pegawai site
        sebelah, atau pegawai di luar cakupan pembuatnya tetap bisa
        dipaksa masuk lewat satu request. Yang tertangkap belakangan
        oleh `document_validations` hanya sebagian — cakupan pembuat
        tidak pernah diperiksa di sana sama sekali.

        Keputusannya diambil dari `eligible_employees()` yang sama
        dengan dropdown; alasannya baru disusun **sesudah** ditolak,
        supaya tidak ada salinan kedua aturan kelayakan yang bisa
        menyimpang dari yang pertama.
        """
        allowed = (
            cls.eligible_employees(request=request, user=user)
            .filter(pk=employee.pk)
            .exists()
        )

        if allowed:
            return

        raise ValidationError(
            {
                "employee": cls.rejection_reason(
                    request=request,
                    employee=employee,
                    user=user,
                ),
            },
        )

    @classmethod
    def rejection_reason(cls, *, request, employee, user=None) -> str:
        """
        Kenapa satu pegawai tidak boleh masuk dokumen ini.

        Hanya jalan di jalur penolakan. "Pegawai itu tidak ada di
        daftar" tidak memberi tahu apa pun kepada orang yang harus
        memperbaikinya — dan lima sebabnya menuntut lima tindakan yang
        berbeda.
        """
        from apps.hr.models import ROSTER_LIVE_STATUSES, SiteRotation

        number = employee.employee_number

        if not employee.is_active or employee.is_deleted:
            return (
                f"{number} sudah tidak aktif, jadi tidak bisa "
                "dijadwalkan. Aktifkan dulu datanya kalau ia memang "
                "masih bekerja."
            )

        employment = getattr(employee, "employment", None)

        if getattr(employment, "termination_date", None):
            return (
                f"{number} sudah berhenti per "
                f"{employment.termination_date}. Jadwal tidak "
                "diterbitkan untuk pegawai yang sudah keluar."
            )

        organization = getattr(employee, "organization", None)

        if getattr(organization, "location_id", None) != request.location_id:
            return (
                f"{number} ditempatkan di "
                f"{getattr(organization, 'location', None) or '—'}, "
                f"bukan di {request.location}. Satu dokumen setup "
                "hanya memuat pegawai site-nya sendiri — pegawai "
                "kantor pusat tidak pernah masuk roster site."
            )

        if (
            request.department_id
            and getattr(organization, "department_id", None)
            != request.department_id
        ):
            return (
                f"{number} bukan pegawai Department "
                f"{request.department}. Kosongkan penyaring "
                "Department kalau dokumen ini memang lintas "
                "department."
            )

        if (
            request.section_id
            and getattr(organization, "section_id", None)
            != request.section_id
        ):
            return (
                f"{number} bukan pegawai Section {request.section}. "
                "Kosongkan penyaring Section kalau dokumen ini memang "
                "lintas section."
            )

        applicable = filter_employees(
            Employee.objects.filter(pk=employee.pk),
            HRFeature.ROSTER,
        ).exists()

        if not applicable:
            group = getattr(employment, "employee_group", None)

            return (
                f"Employee Group \"{getattr(group, 'name', '-')}\" "
                "tidak memakai Roster, jadi "
                f"{number} tidak dijadwalkan. Nyalakan Roster pada "
                "master Employee Group kalau kebijakannya berubah."
            )

        busy = (
            SiteRotation.objects
            .filter(
                employee=employee,
                is_deleted=False,
                effective_to__isnull=True,
                status__in=ROSTER_LIVE_STATUSES,
            )
            .first()
        )

        if busy is not None:
            return (
                f"{number} sudah punya rencana roster berjalan "
                f"({busy}). Tutup atau sesuaikan rencana itu dulu — "
                "dua rencana aktif untuk satu orang berarti dua jadwal "
                "yang saling bertentangan."
            )

        return (
            f"{number} di luar cakupan data Anda. Hubungi "
            "administrator kalau pegawai itu memang tanggung jawab "
            "Anda."
        )

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    @classmethod
    def preview(cls, *, request: RosterSetupRequest) -> dict:
        """
        Preview seluruh baris, **tanpa menulis apa pun**.

        Yang dikembalikan sama persis dengan yang akan disimpan. Kalau
        berbeda, orang menyetujui satu jadwal dan mendapat jadwal yang
        lain.
        """
        lines = (
            request.lines
            .filter(is_deleted=False)
            .select_related(
                "employee",
                "employee__organization",
                "employee__employment",
                "employee__employment__point_of_hire",
                "roster_policy",
            )
            .prefetch_related("roster_policy__travel_days__point_of_hire")
            .order_by("employee__employee_number")
        )

        results = []

        blocking_lines = 0
        warning_lines = 0

        for line in lines:
            preview = RosterGenerationService.preview(
                employee=line.employee,
                policy=line.roster_policy,
                cycle_start=line.current_cycle_start,
                horizon_months=request.horizon_months,
                as_of_date=request.as_of_date,
            )

            levels = {
                item["level"] for item in preview["validations"]
            }

            if "blocking" in levels:
                blocking_lines += 1
            elif "warning" in levels:
                warning_lines += 1

            results.append(
                {
                    "line_id": line.pk,
                    "employee_id": line.employee_id,
                    "employee_number": line.employee.employee_number,
                    "employee_name": line.employee.full_name,
                    "roster_policy_id": line.roster_policy_id,
                    "roster_policy_code": line.roster_policy.code,
                    "current_cycle_start": line.current_cycle_start,
                    "opening_rotation_credit": (
                        line.opening_rotation_credit
                    ),
                    **preview,
                },
            )

        document = cls.document_validations(request=request, lines=lines)

        workflow = cls.workflow_findings(
            request=request,
            lines=lines,
            document=document,
        )

        # Dua pertanyaan, dua jawaban — dan memisahkannya bukan
        # kerapian. `can_commit` menjawab "isinya benar?"; `can_submit`
        # menjawab "bisa dijalankan lewat alurnya?". Seed peragaan
        # commit langsung tanpa approval, jadi ia berhak berjalan pada
        # dokumen yang mejanya bercabang; kalau keduanya digabung, satu
        # dokumen yang atasannya berbeda-beda membuat seed roster tidak
        # menerbitkan satu rencana pun — dan itu terbaca seperti seed
        # yang rusak, bukan seperti aturan yang bekerja.
        can_commit = (
            bool(results)
            and blocking_lines == 0
            and not any(item.level == "blocking" for item in document)
        )

        return {
            "as_of_date": request.as_of_date,
            "horizon_months": request.horizon_months,
            "lines": results,
            "document_validations": [
                item.as_dict() for item in document
            ],
            "workflow_validations": [
                item.as_dict() for item in workflow
            ],
            "total_lines": len(results),
            "blocking_lines": blocking_lines,
            "warning_lines": warning_lines,
            "can_commit": can_commit,
            "can_submit": (
                can_commit
                and not any(item.level == "blocking" for item in workflow)
            ),
        }

    @classmethod
    def document_validations(cls, *, request, lines) -> list:
        """
        Temuan pada **isi** dokumennya, bukan pada barisnya dan bukan
        pada alurnya.

        Yang paling penting: seluruh baris harus di site yang sama.
        Tanpa itu cakupan approver tidak bisa ditentukan.

        Kesiapan **meja persetujuannya** sengaja dipisah ke
        `workflow_findings()`. Dua pertanyaan yang berbeda: "dokumen ini
        benar?" dijawab di sini, "dokumen ini bisa dijalankan lewat
        alurnya?" dijawab di sana — dan ada pemanggil yang memang cuma
        butuh yang pertama, yaitu seed peragaan yang commit langsung
        tanpa approval.
        """
        from apps.hr.api.roster.services import blocking, warning

        findings = []

        if not lines:
            findings.append(
                blocking(
                    "no_lines",
                    "Dokumen ini belum punya satu pun pegawai.",
                ),
            )

            return findings

        if len(lines) > MAX_SETUP_LINES:
            findings.append(
                blocking(
                    "too_many_lines",
                    f"Satu dokumen dibatasi {MAX_SETUP_LINES} pegawai. "
                    "Pecah per Section.",
                ),
            )

        stray = [
            line.employee.employee_number
            for line in lines
            if getattr(
                getattr(line.employee, "organization", None),
                "location_id",
                None,
            )
            != request.location_id
        ]

        if stray:
            findings.append(
                blocking(
                    "mixed_location",
                    "Pegawai berikut tidak ditempatkan di site dokumen "
                    f"ini: {', '.join(stray[:10])}"
                    + ("…" if len(stray) > 10 else "")
                    + ". Satu dokumen setup hanya boleh memuat satu "
                    "site — kalau bercampur, meja persetujuannya tidak "
                    "bisa ditentukan.",
                ),
            )

        duplicates = [
            number
            for number, count in _count(
                line.employee.employee_number for line in lines
            ).items()
            if count > 1
        ]

        if duplicates:
            findings.append(
                blocking(
                    "duplicate_employee",
                    f"Pegawai muncul lebih dari sekali: "
                    f"{', '.join(duplicates)}.",
                ),
            )

        return findings

    @classmethod
    def workflow_findings(cls, *, request, lines, document=None) -> list:
        """
        Temuan pada alur yang akan dilalui dokumen ini.

        Alur yang belum ada **tidak** dilaporkan di sini: itu kesalahan
        konfigurasi tenant, bukan kesalahan dokumennya, dan `submit()`
        sudah menolaknya dengan kalimat yang menyebut jalan keluarnya.
        Memunculkannya di preview cuma membuat setiap dokumen di tenant
        yang alurnya belum diseed terlihat rusak.

        Dokumen yang barisnya masih bercampur site tidak diperiksa sama
        sekali: cakupan approver-nya memang belum bisa ditentukan, jadi
        temuan di sini akan menunjuk sebab yang salah. Temuan isinya
        dioper, bukan dihitung ulang — `document_validations` menyentuh
        database, dan preview memanggil keduanya berurutan.
        """
        if any(item.level == "blocking" for item in document or []):
            return []

        employees = [line.employee for line in lines]

        if not employees:
            return []

        sample = employees[0]

        definition = cls.definition_for(
            scope={
                "company": request.company,
                "branch": getattr(
                    getattr(sample, "organization", None), "branch", None,
                ),
                "location": request.location,
            },
        )

        if definition is None:
            return []

        return cls.batch_approver_findings(
            definition=definition,
            employees=employees,
            company=request.company,
        )

    # ------------------------------------------------------------------
    # Pengajuan
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def submit(cls, *, request: RosterSetupRequest, user=None):
        """
        Mengajukan seluruh dokumen sebagai satu alur.

        Validasi yang sungguhan dijalankan **di sini**, bukan saat
        commit — supaya kegagalannya muncul di layar orang yang bisa
        memperbaikinya. Pola yang sama dengan
        `TravelRequestService.assert_no_leave_conflict`.
        """
        from apps.workflow.services.workflow_service import WorkflowService

        if request.status not in {
            RosterSetupStatus.DRAFT,
            RosterSetupStatus.REJECTED,
        }:
            raise ValidationError(
                {
                    "status": (
                        f"Dokumen berstatus "
                        f"{request.get_status_display()} tidak bisa "
                        "diajukan lagi."
                    ),
                },
            )

        preview = cls.preview(request=request)

        if not preview["can_submit"]:
            messages = [
                item["message"]
                for item in (
                    preview["document_validations"]
                    + preview["workflow_validations"]
                )
                if item["level"] == "blocking"
            ]

            for row in preview["lines"]:
                for item in row["validations"]:
                    if item["level"] == "blocking":
                        messages.append(
                            f"{row['employee_number']}: {item['message']}",
                        )

            raise ValidationError({"roster": messages})

        sample = cls.sample_employee(request)

        scope = {
            "company": request.company,
            "branch": getattr(
                getattr(sample, "organization", None), "branch", None,
            ),
            "location": request.location,
        }

        cls.assert_batch_definition_supported(
            scope=scope,
            employees=[
                line.employee
                for line in request.lines
                .filter(is_deleted=False)
                .select_related("employee", "employee__organization")
                .order_by("employee__employee_number")
            ],
        )

        instance = WorkflowService.submit(
            document=request,
            module=MODULE,
            document_type=DOCUMENT_TYPE,
            # Sengaja tanpa `employee=`: dokumen setup adalah dokumen
            # perencanaan HR, bukan dokumen milik satu pegawai. Yang
            # dipakai menyusun approver adalah sampel organisasi di
            # bawah, dan itu sah karena seluruh baris ada di satu site.
            employee=sample,
            # Pengusulnya: Admin Department / Admin Section yang
            # menyusun dokumen ini. Kalau ia kebetulan juga memegang
            # salah satu meja, meja itu ditandai SKIPPED — pembuat
            # tidak diminta menyetujui usulannya sendiri, aturan yang
            # sama dengan alur site untuk Cuti dan Travel Request.
            initiator_employee=getattr(user, "employee_profile", None),
            user=user,
            scope=scope,
            document_number=request.document_number,
            document_label=cls.document_label(request, preview),
            context={
                "total_lines": preview["total_lines"],
                "location_id": request.location_id,
                "section_id": request.section_id,
                "as_of_date": str(request.as_of_date),
            },
            on_complete=lambda inst, status: cls.on_workflow_done(
                request=request,
                status=status,
                user=user,
            ),
        )

        request.status = RosterSetupStatus.SUBMITTED
        request.submitted_at = timezone.now()
        request.submitted_by = user

        request.save(
            update_fields=[
                "status",
                "submitted_at",
                "submitted_by",
                "updated_at",
            ],
        )

        return instance

    @staticmethod
    def sample_employee(request: RosterSetupRequest):
        """
        Pegawai yang penempatannya dipakai menentukan cakupan approver.

        **Bukan** subjek dokumen — dokumen ini milik HR, bukan milik
        seseorang. Ia cuma contoh penempatan, dan itu sah karena
        seluruh baris berada di site yang sama (dijaga
        `document_validations`). Dipilih deterministik supaya dua submit
        yang sama menghasilkan approver yang sama; kalau diacak,
        "kenapa yang menandatangani orang ini" tidak punya jawaban.

        Untuk step yang berangkat dari pegawai — meja atasan langsung —
        ia bukan cuma deterministik tapi **terbukti mewakili**:
        `batch_approver_findings` sudah menolak dokumen yang barisnya
        jatuh ke lebih dari satu atasan sebelum submit sampai ke sini.
        """
        line = (
            request.lines
            .filter(is_deleted=False)
            .select_related("employee", "employee__organization")
            .order_by("employee__employee_number")
            .first()
        )

        return line.employee if line is not None else None

    @staticmethod
    def document_label(request, preview) -> str:
        parts = [
            "Roster Setup",
            str(request.location),
        ]

        if request.section_id:
            parts.append(str(request.section))

        parts.append(f"{preview['total_lines']} pegawai")
        parts.append(f"as of {request.as_of_date}")

        return " — ".join(parts)

    @classmethod
    def definition_for(cls, *, scope):
        """Alur yang akan dipakai dokumen dengan cakupan ini, atau None."""
        from apps.workflow.services import WorkflowDefinitionResolver

        return WorkflowDefinitionResolver.match(
            module=MODULE,
            document_type=DOCUMENT_TYPE,
            **scope,
        )

    @classmethod
    def assert_batch_definition_supported(cls, *, scope, employees=None):
        """
        Memeriksa alurnya **bisa dijalankan untuk batch ini**.

        Dulu step bertipe per-pegawai (`manager`/`department_head`/
        `position`) ditolak mentah-mentah: dokumen batch tidak punya satu
        pegawai subjek, jadi seluruh mejanya wajib bertipe Role. Aturan
        itu terlalu keras, dan yang dibuangnya justru meja yang paling
        diminta — persetujuan **atasan langsung** pegawai yang
        dijadwalkan.

        Yang menggantikannya bukan pelonggaran, melainkan syarat yang
        lebih tepat: sebuah step per-pegawai boleh dipakai **kalau
        seluruh baris dokumen ini menghasilkan approver yang sama**.
        Kalau ya, sampel organisasi yang dipakai `submit()` bukan lagi
        "salah satu yang kebetulan" — ia terbukti mewakili seluruh
        batch. Kalau tidak, dokumennya ditolak dengan menyebut siapa
        saja atasannya dan pegawai siapa, supaya batch-nya dipecah per
        atasan — bukan diam-diam dijatuhkan ke satu nama.

        `employees=None` hanya memeriksa keberadaan alurnya. Dipakai
        pemanggil yang memang cuma ingin tahu apakah dokumen dengan
        cakupan ini punya alur sama sekali.
        """
        definition = cls.definition_for(scope=scope)

        if definition is None:
            raise ValidationError(
                {
                    "workflow": (
                        "Belum ada alur aktif untuk setup roster yang "
                        "cocok dengan site ini. Seed lewat "
                        "seed_workflows, atau buat di layar Workflow "
                        "Definition."
                    ),
                },
            )

        if not employees:
            return definition

        findings = cls.batch_approver_findings(
            definition=definition,
            employees=employees,
            company=scope.get("company"),
        )

        messages = [
            item.message for item in findings if item.level == "blocking"
        ]

        if messages:
            raise ValidationError({"workflow": messages})

        return definition

    @classmethod
    def batch_approver_findings(
        cls,
        *,
        definition,
        employees,
        company=None,
    ) -> list:
        """
        Temuan pada meja-meja yang berangkat dari **satu** pegawai.

        Dijalankan lewat `resolve_approvers()` yang sama dengan yang
        dipakai engine saat submit — bukan lewat salinan aturan garis
        pelaporan di sini. Salinan kedua akan menyimpang diam-diam, dan
        yang menyimpang adalah pemeriksaan yang seharusnya menjaga.

        Step bertipe Role/User dilewati: keduanya memang tidak membaca
        pegawai subjek, jadi batch berapa pun besarnya menghasilkan meja
        yang sama.
        """
        from apps.workflow.resolver import resolve_approvers

        from apps.hr.api.roster.services import blocking

        findings = []

        steps = [
            step
            for step in definition.steps.filter(
                is_deleted=False, is_active=True,
            ).order_by("sequence")
            if step.approver_type in PER_EMPLOYEE_APPROVER_TYPES
        ]

        if not steps:
            return findings

        employees = list(employees)

        for step in steps:
            # `{user_id: (label, [nomor pegawai])}` — dikelompokkan
            # supaya pesannya bisa menyebut siapa membawahi siapa.
            # Tanpa itu "atasannya berbeda" tidak memberi tahu batch ini
            # harus dipecah jadi berapa.
            groups: dict = {}
            missing: list[str] = []

            for employee in employees:
                resolved = resolve_approvers(
                    employee=employee,
                    step=step,
                    company=company,
                )

                if not resolved.found:
                    missing.append(employee.employee_number)

                    continue

                for candidate in resolved.candidates:
                    label, numbers = groups.setdefault(
                        candidate.user.pk,
                        (cls._approver_label(candidate), []),
                    )

                    numbers.append(employee.employee_number)

            if missing and step.is_required:
                findings.append(
                    blocking(
                        "approver_not_found",
                        f"Step #{step.sequence} \"{step.name}\" tidak "
                        "menemukan approver untuk "
                        f"{_names(missing)}. Lengkapi kolom yang "
                        "dibacanya — untuk meja atasan langsung, "
                        "'Reports To' pada penempatan organisasi "
                        "pegawai itu.",
                    ),
                )

            if len(groups) > 1:
                detail = "; ".join(
                    f"{label} → {_names(numbers)}"
                    for label, numbers in groups.values()
                )

                findings.append(
                    blocking(
                        "mixed_approver",
                        f"Step #{step.sequence} \"{step.name}\" "
                        "berangkat dari pegawai yang dijadwalkan, dan "
                        "dokumen ini memuat "
                        f"{len(groups)} meja yang berbeda: {detail}. "
                        "Pecah dokumen ini per atasan — satu dokumen, "
                        "satu meja. Memilih salah satunya berarti satu "
                        "orang menandatangani jadwal bawahan orang "
                        "lain, dan yang tidak menandatangani tidak "
                        "pernah tahu jadwal timnya berubah.",
                    ),
                )

        return findings

    @staticmethod
    def _approver_label(candidate) -> str:
        employee = getattr(candidate, "employee", None)

        if employee is not None:
            return f"{employee.employee_number} {employee.full_name}"

        return str(getattr(candidate.user, "username", candidate.user))

    @classmethod
    @transaction.atomic
    def withdraw(cls, *, request: RosterSetupRequest, user=None):
        from apps.workflow.services.workflow_service import WorkflowService

        if request.status != RosterSetupStatus.SUBMITTED:
            raise ValidationError(
                {
                    "status": (
                        "Hanya dokumen yang sedang menunggu persetujuan "
                        "yang bisa ditarik."
                    ),
                },
            )

        instance = WorkflowService.instance_for(
            document=request,
            module=MODULE,
            document_type=DOCUMENT_TYPE,
        )

        if instance is None:
            raise ValidationError(
                {"status": "Tidak ada pengajuan yang bisa ditarik."},
            )

        WorkflowService.cancel(
            instance=instance,
            user=user,
            comment="Ditarik oleh pengaju.",
        )

        request.status = RosterSetupStatus.DRAFT

        request.save(update_fields=["status", "updated_at"])

        return request

    # ------------------------------------------------------------------
    # Penyelesaian alur → commit
    # ------------------------------------------------------------------

    @classmethod
    def on_workflow_done(cls, *, request, status, user=None):
        """
        Dipanggil engine saat alurnya berhenti.

        Kegagalan commit **tidak** membatalkan persetujuan: alurnya
        sudah selesai dan keputusan approver-nya sah, dan melempar di
        titik ini menampilkan error pada orang yang tidak bisa
        memperbaikinya. Yang gagal ditempel ke barisnya sendiri dan
        diulang lewat `POST .../commit/`.
        """
        from apps.workflow.models import InstanceStatus

        if status == InstanceStatus.APPROVED:
            request.status = RosterSetupStatus.APPROVED

            request.save(update_fields=["status", "updated_at"])

            return cls.commit(request=request, user=user)

        mapping = {
            InstanceStatus.REJECTED: RosterSetupStatus.REJECTED,
            InstanceStatus.CANCELLED: RosterSetupStatus.CANCELLED,
            InstanceStatus.RETURNED: RosterSetupStatus.DRAFT,
        }

        request.status = mapping.get(status, request.status)

        request.save(update_fields=["status", "updated_at"])

        return request

    @classmethod
    def commit(cls, *, request: RosterSetupRequest, user=None):
        """
        Menerbitkan rencana untuk tiap baris.

        Per baris di dalam savepoint sendiri: satu baris yang gagal
        tidak boleh membatalkan dua puluh sembilan lainnya. Yang gagal
        ditandai `FAILED` beserta alasannya, dan `commit` bisa
        dijalankan ulang — ia melewati baris yang sudah `COMMITTED`.
        """
        lines = (
            request.lines
            .filter(is_deleted=False)
            .exclude(status=RosterSetupLineStatus.COMMITTED)
            .select_related(
                "employee",
                "employee__organization",
                "employee__employment",
                "roster_policy",
            )
            .order_by("employee__employee_number")
        )

        committed = 0
        failed = 0

        for line in lines:
            try:
                with transaction.atomic():
                    cls.commit_line(line=line, request=request, user=user)

                committed += 1
            except Exception as error:  # noqa: BLE001
                failed += 1

                line.status = RosterSetupLineStatus.FAILED
                line.commit_error = str(error)[:2000]

                line.save(
                    update_fields=[
                        "status",
                        "commit_error",
                        "updated_at",
                    ],
                )

                logger.exception(
                    "Gagal commit baris setup roster %s (pegawai %s).",
                    line.pk,
                    line.employee_id,
                )

        already = (
            request.lines
            .filter(
                is_deleted=False,
                status=RosterSetupLineStatus.COMMITTED,
            )
            .count()
        )

        request.status = (
            RosterSetupStatus.COMMITTED
            if failed == 0
            else RosterSetupStatus.PARTIALLY_COMMITTED
        )

        request.committed_at = timezone.now()

        request.commit_error = (
            ""
            if failed == 0
            else (
                f"{failed} baris gagal diterbitkan. Perbaiki datanya "
                "lalu jalankan Commit lagi — baris yang sudah berhasil "
                "tidak diulang."
            )
        )

        request.save(
            update_fields=[
                "status",
                "committed_at",
                "commit_error",
                "updated_at",
            ],
        )

        logger.info(
            "Setup roster %s: %s baris diterbitkan, %s gagal, %s sudah ada.",
            request.pk,
            committed,
            failed,
            already - committed,
        )

        return request

    @classmethod
    def commit_line(cls, *, line: RosterSetupLine, request, user=None):
        """
        Satu baris → satu rencana + baseline + saldo awal.

        Pemeriksaan tumpang tindih diulang di sini walau preview sudah
        melakukannya: di antara keduanya bisa ada dokumen lain yang
        disetujui duluan, dan yang menang adalah yang lebih dulu
        di-commit.
        """
        from apps.hr.api.roster.credit_service import RotationCreditService

        findings = RosterValidator.check(
            employee=line.employee,
            policy=line.roster_policy,
            cycle_start=line.current_cycle_start,
            as_of_date=request.as_of_date,
        )

        blocked = [
            item.message
            for item in findings
            if item.level == "blocking"
        ]

        if blocked:
            raise ValidationError({"roster": blocked})

        plan = RosterGenerationService.commit(
            employee=line.employee,
            policy=line.roster_policy,
            cycle_start=line.current_cycle_start,
            horizon_months=request.horizon_months,
            as_of_date=request.as_of_date,
            setup_line=line,
            user=user,
            status=SiteRotationStatus.APPROVED,
        )

        RosterGenerationService.lock_baseline(plan=plan, user=user)

        # Penempatan pegawai ikut diperbarui: rencana yang terbit tanpa
        # menyentuh assignment membuat form pegawai menampilkan keadaan
        # yang berbeda dari jadwalnya sendiri.
        employment = getattr(line.employee, "employment", None)

        if employment is not None:
            employment.roster_policy = line.roster_policy
            employment.roster_cycle_start = line.current_cycle_start

            employment.save(
                update_fields=[
                    "roster_policy",
                    "roster_cycle_start",
                    "updated_at",
                ],
            )

        if line.opening_rotation_credit:
            RotationCreditService.open_balance(
                employee=line.employee,
                days=line.opening_rotation_credit,
                effective_date=request.as_of_date,
                reason=(
                    line.note
                    or f"Saldo awal dari dokumen {request.document_number}."
                ),
                source_type="roster_setup",
                source_id=request.pk,
                user=user,
            )

        line.status = RosterSetupLineStatus.COMMITTED
        line.commit_error = ""

        line.save(
            update_fields=["status", "commit_error", "updated_at"],
        )

        return plan


class RosterSetupLineService(BaseMasterService):
    model = RosterSetupLine

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        request = data.get("request")

        if request is not None:
            RosterSetupService.assert_editable(request)

            employee = data.get("employee")

            if employee is not None:
                RosterSetupService.assert_employee_allowed(
                    request=request,
                    employee=employee,
                    user=user,
                )

        return cls.apply_defaults(data)

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        RosterSetupService.assert_editable(instance.request)

        # Mengganti pegawai sebuah baris adalah penambahan yang
        # menyamar: kalau hanya `create` yang dijaga, satu PATCH
        # menaruh pegawai kantor pusat di baris yang sudah lolos
        # pemeriksaan.
        employee = data.get("employee")

        if employee is not None and employee.pk != instance.employee_id:
            RosterSetupService.assert_employee_allowed(
                request=instance.request,
                employee=employee,
                user=user,
            )

        return data

    @staticmethod
    def apply_defaults(data: dict[str, Any]) -> dict[str, Any]:
        """
        Mengisi policy dan jangkar dari penempatan pegawai kalau form
        tidak menyebutkannya.

        Bukan supaya bisa dikosongkan, melainkan supaya baris yang
        pegawainya sudah pernah disetup tidak perlu diketik ulang.
        """
        employee = data.get("employee")

        if employee is None:
            return data

        employment = getattr(employee, "employment", None)

        if employment is None:
            return data

        if not data.get("roster_policy") and employment.roster_policy_id:
            data["roster_policy"] = employment.roster_policy

        if (
            not data.get("current_cycle_start")
            and employment.roster_cycle_start
        ):
            data["current_cycle_start"] = employment.roster_cycle_start

        return data


def _names(values, limit: int = 10) -> str:
    """Daftar nomor pegawai yang dipotong, supaya pesannya tetap terbaca."""
    values = list(values)

    shown = ", ".join(values[:limit])

    if len(values) > limit:
        shown += f" (+{len(values) - limit} lagi)"

    return shown


def _count(values) -> dict:
    result: dict = {}

    for value in values:
        result[value] = result.get(value, 0) + 1

    return result
