
from django.db.models import Q
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from apps.hr.models import (
    Employee,
    OrganizationAssignment,
)

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet

from apps.hr.api.employee.filters import EmployeeFilterSet
from apps.hr.applicability import filter_employees
from apps.hr.api.employee.views.employment_history import (
    employment_timeline,
)

from apps.hr.api.employee.schema import EMPLOYEE_SCHEMA
from apps.hr.api.employee.scope import EMPLOYEE_SCOPE
from apps.hr.api.employee.serializers.employee import EmployeeSerializer
from apps.hr.api.employee.services.employee_service import EmployeeService
from apps.accounts.permissions import required_view_permission
from apps.accounts.scoping import DataScopeService


class EmployeeViewSet(BaseMasterViewSet):
    # Employee menyimpan organisasinya di relasi `organization`
    # (OrganizationAssignment), bukan di kolomnya sendiri. Petanya
    # dipegang `apps.hr.api.employee.scope` — dipakai bersama importer
    # absensi, dan satu salinan lagi di sini adalah persis cara dua
    # layar mulai menyaring dengan aturan yang berbeda.
    # Sensitif: baca ikut menuntut `view_<model>`. Lihat
    # `BaseMasterViewSet.require_view_permission`.
    require_view_permission = True

    data_scope = EMPLOYEE_SCOPE

    serializer_class = EmployeeSerializer
    service_class = EmployeeService

    framework_module = "hr/employees"
    schema_type = "crud"

    ordering = [
        "first_name",
        "last_name",
    ]

    search_fields = [
        "employee_number",
        "nik",
        "first_name",
        "last_name",
        "personal_email",
        "work_email",
        "phone",
        "mobile",
    ]

    # Memakai FilterSet karena filter organisasi harus menembus relasi
    # `organization` (lihat apps/hr/api/employee/filters.py).
    filterset_class = EmployeeFilterSet

    schema = EMPLOYEE_SCHEMA

    # `full_name` dan `display_name` adalah properti turunan — keduanya
    # dirangkai dari `first_name` + `last_name` yang sudah punya
    # kolomnya sendiri di file export. Mereka tidak pernah jadi kolom
    # tabel di layar (generator FE tidak menghasilkannya), jadi selama
    # ini muncul **hanya** di CSV: tiga kolom untuk satu nama yang sama.
    #
    # Ditulis sebagai **union** dengan milik base, bukan set baru.
    # Menimpanya begitu saja akan mengembalikan `id`, `created_at`, dan
    # seluruh kolom audit ke dalam file export — jebakan yang sama
    # dengan `permission_classes` yang mengganti alih-alih menambah.
    EXPORT_EXCLUDED_FIELDS = (
        BaseMasterViewSet.EXPORT_EXCLUDED_FIELDS
        | {
            "full_name",
            "display_name",
        }
    )

    def get_queryset(self):
        return EmployeeService.list()

    def get_export_fields(self, request):
        """
        Kolom yang tidak boleh dilihat pembacanya dibuang dari CSV.

        **Export membaca nilainya langsung dari instance**
        (`resolve_export_value`), bukan lewat serializer — jadi masking
        di `EmployeeSerializer` tidak menyentuhnya sama sekali, dan
        tanpa baris ini seluruh kolom gaji keluar utuh lewat satu
        tombol Export di sebelah tabel yang justru sudah menutupnya.

        **Kolomnya dibuang seluruhnya, bukan dikosongkan per baris.**
        CSV yang sebagian selnya terisi dan sebagian kosong justru
        membocorkan polanya — pembacanya tahu persis pegawai mana yang
        datanya dibatasi, dan itu setengah dari informasinya. Jadi satu
        baris saja yang tidak boleh dilihat sudah cukup untuk membuang
        kolomnya.
        """
        columns = super().get_export_fields(request)

        user = getattr(request, "user", None)

        if user is None or getattr(user, "is_superuser", False):
            return columns

        from apps.administration.models import SUBJECT_EMPLOYEE_FIELDS
        from apps.hr.api.employee.visibility import EmployeeDataVisibility

        queryset = self.filter_queryset(self.get_queryset())

        hidden: set[str] = set()

        for subject, field_names in SUBJECT_EMPLOYEE_FIELDS.items():
            allowed = EmployeeDataVisibility.visible_employees_q(
                subject=str(subject),
                user=user,
            )

            if allowed is None:
                continue

            # Satu EXISTS per kelompok yang memang punya aturan, bukan
            # satu query per baris.
            if queryset.exclude(allowed).exists():
                hidden.update(field_names)

        if not hidden:
            return columns

        return [
            (name, label)
            for name, label in columns
            if name not in hidden
        ]

    @action(
        detail=False,
        methods=["get"],
        url_path="me",
    )
    def me(self, request):
        """
        Kartu pegawai milik pengguna yang sedang login.

        Dipakai layar **My Profile** (`/hr/my-profile`), yang read-only:
        tidak ada satu pun jalur tulis di sini, dan itu bukan tombol
        Save yang disembunyikan — endpoint-nya memang cuma GET.

        **Kenapa endpoint tersendiri, bukan memakai daftar biasa.**
        `GET /api/hr/employees/` memang sudah mengembalikan tepat satu
        baris untuk pegawai biasa (cakupan `own`), tapi bentuknya
        daftar — dan bentuk itu bohong: yang dikembalikan "satu baris
        kalau cakupannya kebetulan sempit". Untuk HR Manager yang
        cakupannya seluruh tenant, daftar yang sama berisi sebelas
        baris dan tidak ada satu pun yang menandai mana dirinya.
        `me/` menjawab pertanyaan yang berbeda, jadi ia endpoint yang
        berbeda.

        Disaring lewat `user`, **bukan** lewat `filter_queryset()`:
        kartu sendiri tidak boleh bisa disembunyikan oleh cakupan
        data. Admin yang dicakup ke satu lokasi lalu dipindahkan ke
        lokasi lain tetap harus bisa membuka datanya sendiri — kalau
        lewat cakupan, ia justru kehilangan halamannya tanpa satu pun
        pesan yang menyebut sebabnya.

        Penyaringan **kolomnya** tetap berlaku: `EmployeeSerializer`
        membaca `EmployeeDataPolicy` dari `request.user`, jadi kelompok
        yang tidak boleh ia lihat dari dirinya sendiri tetap dibuang
        dari payload.
        """
        employee = (
            self.get_queryset()
            .filter(user=request.user)
            .first()
        )

        # Akun tanpa kartu pegawai adalah keadaan yang sah dan lazim —
        # admin sistem, akun integrasi, akun yang dibuat sebelum
        # pegawainya didaftarkan. Dibalas 404 dengan kalimat yang
        # menyebut sebabnya, bukan 500 atau objek kosong yang terbaca
        # seperti data yang gagal dimuat.
        if employee is None:
            raise NotFound(
                "Akun ini belum ditautkan ke data pegawai mana pun. "
                "Hubungi HR untuk menghubungkan akun Anda ke kartu "
                "pegawai."
            )

        serializer = self.get_serializer(employee)

        return success_response(
            data=self.with_lookup_labels(employee, serializer.data),
        )

    def with_lookup_labels(self, employee, data):
        """
        Isi `<field>_name` untuk field lookup yang belum punya.

        `EmployeeSerializer` mengirim `<x>_name` hanya untuk sebelas dari
        tiga puluh tiga field lookup-nya. Di form admin itu tidak terasa:
        `MLookupField` menyelesaikan labelnya sendiri lewat endpoint
        lookup. Tapi layar baca tidak punya jalan itu, jadi kolomnya
        mencetak **pk mentah** — "Department: 10", "Position: 14",
        "User Account: 70". Angka yang tidak berarti apa-apa bagi yang
        membacanya, dan lebih buruk daripada kosong: ia terlihat seperti
        data yang benar.

        **Diisi di sini, bukan dengan menambah enam belas field ke
        serializer.** Serializer itu dipakai bersama tabel dan export,
        dan field `<x>_name` hasil introspeksi lolos penyaring kolom
        export (`table` tidak disebut = ikut). Menambahkannya di sana
        akan mengembalikan enam belas kolom ke CSV — persis kebalikan
        dari pembersihan yang baru saja diminta.

        **Sumbernya peta `source` milik serializer**, mesin yang sama
        dengan export (`get_export_sources` + `resolve_export_value`).
        Dua penyelesai label yang harus tetap sama adalah persis cara
        satu nilai tampil sebagai nama di satu layar dan sebagai angka
        di layar lain — dan `department` di sini memang bersumber
        `organization.department`, bukan atribut milik Employee.

        Berlaku untuk **seluruh** field lookup di schema, bukan empat
        yang kebetulan terisi hari ini: dua belas sisanya kosong di
        record ini dan akan menampilkan angka yang sama begitu diisi.
        """
        payload = dict(data)

        sources = self.get_export_sources()
        fields = (self.schema or {}).get("fields", {}) or {}

        for key, config in fields.items():
            if (config or {}).get("type") != "lookup":
                continue

            label_key = f"{key}_name"

            # Yang sudah dikirim serializer tidak disentuh — di situ
            # `display_key` pada schema sudah menunjuk kuncinya, dan
            # menimpanya berarti dua sumber untuk satu label.
            if label_key in payload:
                continue

            if payload.get(key) in (None, ""):
                continue

            label = self.resolve_export_value(
                employee,
                sources.get(key, key),
            )

            if label:
                payload[label_key] = label

        return payload

    @action(
        detail=True,
        methods=["get"],
        url_path="employment-history",
    )
    def employment_history(self, request, pk=None):
        """
        Riwayat kepegawaian — tab History di workspace Employee.

        `get_object()` sengaja dipakai, bukan `Employee.objects.get()`:
        ia melewati `filter_queryset()`, jadi cakupan data
        (kewenangan `RoleAssignment`) ikut berlaku. Tanpa itu riwayat kontrak
        dan gaji seluruh tenant terbaca lewat satu URL yang ditebak.

        Cakupan data menjawab "**baris** yang mana", dan itu tidak
        cukup: begitu seorang pegawai masuk cakupan admin site, seluruh
        riwayatnya ikut terbaca — kenaikan gaji, demosi, alasan
        pengunduran diri. `viewer=` yang menjawab "**bagian mana** dari
        baris itu", lewat `EmployeeDataPolicy`.
        """
        employee = self.get_object()

        return success_response(
            data={
                "results": employment_timeline(
                    employee,
                    viewer=request.user,
                ),
            },
        )

    @action(detail=False,methods=["get"],url_path="lookup")
    def lookup(self, request):
        # `?feature=roster` (attendance / shift / field_break / …)
        # menyaring daftarnya ke pegawai yang proses itu memang berlaku
        # baginya — sumbernya Feature Applicability di master Employee
        # Group, bukan cabang `if group.code == "BOARD"` di layar yang
        # kebetulan ingat memasangnya.
        #
        # Tanpa param, daftarnya utuh. Itu yang membuat satu endpoint
        # ini tetap bisa dipakai Employee Master, Org Chart, dan
        # Reporting Line: applicability memutuskan siapa yang **diproses**
        # sebuah fitur, bukan siapa yang boleh terbit sebagai pegawai.

        # Dropdown adalah jalur bocor yang paling gampang terlewat: ia
        # merakit querysetnya sendiri dari `Employee.objects`, jadi tidak
        # melewati `filter_queryset()` dan tidak ikut tersaring cakupan
        # data. Tanpa baris `DataScopeService.filter` di bawah, admin
        # site yang hanya boleh melihat 6 pegawai tetap mendapat daftar
        # nama seluruh tenant begitu ia membuka dropdown "pilih pegawai".
        base = (
            Employee.objects
            .filter(
                is_active=True,
                is_deleted=False,
            )
            # Dipakai `autofill` di grid Roster Setup. Tanpa relasi ini
            # dropdown-nya tetap jalan tapi Roster Policy dan Current
            # Cycle Start tidak pernah terisi — gagal tanpa suara,
            # jebakan yang sama dengan `roster_crew` di form Employee.
            .select_related("employment")
            .order_by(
                "first_name",
                "last_name",
            )
        )

        queryset = DataScopeService.filter(
            base,
            self.data_scope,
            request.user,
            # Sama dengan daftarnya. Dropdown yang menjawab pertanyaan
            # yang sama dengan tabelnya harus menjawabnya dengan aturan
            # yang sama — kalau tidak, yang tidak muncul di tabel tetap
            # bisa dipilih dari dropdown, dan bedanya tidak terlihat
            # siapa pun.
            required_permission=required_view_permission(self),
        )

        # `?reporting_line=1` menambahkan bawahan pemanggilnya,
        # berjenjang. **Opt-in, dan hanya menambah**: tanpa param,
        # dropdown ini menghasilkan baris yang sama persis seperti
        # sebelumnya, jadi Employee Master, Org Chart, dan Reporting Line
        # tidak ikut berubah. Param-nya tidak bisa dipakai membuka data
        # orang lain — yang paling jauh bisa didapat seseorang adalah
        # bawahannya sendiri.
        #
        # Dipakai layar Shift Calendar: supervisor yang cakupannya `own`
        # hanya menemukan dirinya sendiri di dropdown, padahal justru
        # jadwal timnya yang harus ia pantau.
        if _flag(request.query_params.get("reporting_line")):
            from apps.hr import reporting_line

            queryset = reporting_line.widen(
                queryset,
                base=base,
                user=request.user,
            )

        queryset = filter_employees(
            queryset,
            request.query_params.get("feature"),
        )

        # Penyempit penempatan, dan **hanya kalau diminta**. Tanpa
        # param, daftarnya utuh persis seperti sebelumnya — itu yang
        # membuat Employee Master, Org Chart, dan Reporting Line tidak
        # ikut berubah perilakunya.
        #
        # Ini penyaring **kenyamanan**, bukan pengaman: yang menentukan
        # siapa yang boleh terbit tetap `DataScopeService.filter` di
        # atas. Layar yang mengirim `?location=` cuma mempersempit
        # daftar yang memang sudah boleh dilihat orang itu.
        #
        # Dibaca dari `OrganizationAssignment` yang aktif, sumber yang
        # sama dengan kolom company/location di hasilnya — kalau
        # dibaca dari tempat lain, dropdown-nya bisa menyaring memakai
        # penempatan yang berbeda dari yang tercetak di barisnya.
        for param, path in (
            ("company", "organization__company_id"),
            ("branch", "organization__branch_id"),
            ("location", "organization__location_id"),
        ):
            raw = request.query_params.get(param)

            if not raw:
                continue

            try:
                value = int(raw)
            except (TypeError, ValueError):
                # Id yang tidak berupa angka diabaikan, bukan 400:
                # pemanggilnya dropdown, dan satu param salah ketik
                # tidak boleh mematikan seluruh daftar nama.
                continue

            queryset = queryset.filter(**{path: value})

        search = str(
            request.query_params.get(
                "search",
                "",
            )
        ).strip()

        if search:
            queryset = queryset.filter(
                Q(
                    employee_number__icontains=search,
                )
                | Q(
                    nik__icontains=search,
                )
                | Q(
                    first_name__icontains=search,
                )
                | Q(
                    last_name__icontains=search,
                )
                | Q(
                    personal_email__icontains=search,
                )
                | Q(
                    work_email__icontains=search,
                )
                | Q(
                    phone__icontains=search,
                )
                | Q(
                    mobile__icontains=search,
                )
            )

        page = self.paginate_queryset(
            queryset,
        )

        employees = list(
            page
            if page is not None
            else queryset
        )

        employee_ids = [
            employee.id
            for employee in employees
        ]

        assignments = (
            OrganizationAssignment.objects
            .filter(
                employee_id__in=employee_ids,
                is_active=True,
                is_deleted=False,
            )
            .select_related(
                "company",
                "branch",
                "location",
            )
            .order_by(
                "employee_id",
                "-organization_effective_date",
                "-id",
            )
        )

        assignment_map: dict[int, OrganizationAssignment] = {}

        for assignment in assignments:
            if (
                assignment.employee_id
                not in assignment_map
            ):
                assignment_map[
                    assignment.employee_id
                ] = assignment

        results = []

        for employee in employees:
            assignment = assignment_map.get(
                employee.id,
            )

            company = (
                assignment.company
                if assignment
                else None
            )

            branch = (
                assignment.branch
                if assignment
                else None
            )

            location = (
                assignment.location
                if assignment
                else None
            )

            employment = getattr(employee, "employment", None)

            display_name = (
                employee.display_name
                or employee.full_name
                or employee.employee_number
            )

            results.append(
                {
                    "id": employee.id,
                    "value": employee.id,
                    "name": display_name,
                    "label": (
                        f"{employee.employee_number} - "
                        f"{display_name}"
                    ),

                    "company": (
                        company.id
                        if company
                        else None
                    ),
                    "company_label": (
                        company.name
                        if company
                        else None
                    ),

                    "branch": (
                        branch.id
                        if branch
                        else None
                    ),
                    "branch_label": (
                        branch.name
                        if branch
                        else None
                    ),

                    "location": (
                        location.id
                        if location
                        else None
                    ),
                    "location_label": (
                        location.name
                        if location
                        else None
                    ),

                    # Pola roster pegawai, dipakai `autofill` di grid
                    # Roster Setup supaya baris yang pegawainya sudah
                    # pernah disetup tidak perlu diketik ulang.
                    "roster_policy": getattr(
                        employment, "roster_policy_id", None,
                    ),
                    "roster_cycle_start": getattr(
                        employment, "roster_cycle_start", None,
                    ),
                }
            )

        if page is not None:
            return self.get_paginated_response(
                results,
            )

        return Response(
            {
                "count": len(results),
                "next": None,
                "previous": None,
                "results": results,
            }
        )


def _flag(raw) -> bool:
    """
    Query param boolean dari dropdown.

    Longgar dengan sengaja: yang mengirimnya URL, dan `1` / `true` /
    `yes` sama-sama wajar diketik orang. Nilai yang tidak dikenal
    dianggap **tidak** menyalakan — param yang salah ketik tidak boleh
    diam-diam memperluas apa yang terlihat.
    """
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}
