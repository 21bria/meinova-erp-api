"""
Membaca `EmployeeDataPolicy`: bagian mana dari data seorang pegawai yang
boleh dilihat oleh akun yang sedang membuka layarnya.

Dipisah dari service karena dijawab di lebih dari satu tempat — hari ini
tab History, berikutnya tab Payroll dan kolom export.

**Menyembunyikan di frontend bukan penjagaan.** Endpoint-nya tetap bisa
ditembak langsung, jadi penyaringannya harus terjadi di sini, dan yang
tidak boleh dilihat **dibuang dari payload** — bukan dikirim lalu
ditutup dengan CSS.

Satu keputusan yang perlu disadari: yang disembunyikan hilang **tanpa
jejak**. Tidak ada baris "3 perubahan disembunyikan", karena penanda
seperti itu sudah memberi tahu bahwa ada kenaikan gaji — dan itu
setengah dari informasinya.
"""

from __future__ import annotations

from apps.administration.models import (
    EmployeeDataPolicy,
    subject_for_action,
)


class EmployeeDataVisibility:
    # ------------------------------------------------------------------
    # Pencocokan aturan
    # ------------------------------------------------------------------

    @staticmethod
    def matches(*, employee, subject: str) -> list[EmployeeDataPolicy]:
        """
        Aturan yang mengatur pegawai ini — **semuanya**, bukan satu.

        Tingkatnya dipilih lewat skor `specificity`, bukan urutan baris:
        siapa yang boleh membaca riwayat gaji seseorang tidak boleh
        bergantung pada nomor id di database. Yang berubah di Stage
        3A.1 adalah apa yang dikembalikan pada tingkat itu — dulu satu
        baris (`max`), sekarang **seluruh** baris di tingkat teratas,
        supaya "HR Manager dan Finance Manager sama-sama boleh" bisa
        ditulis sebagai dua baris.

        Satu tingkat = satu sasaran, dan itu bukan kebetulan: skornya
        4/2/1, jadi dua baris berskor sama pasti mengisi field sasaran
        yang sama persis. Karena keduanya juga sama-sama cocok untuk
        pegawai ini, nilainya pun sama. Jadi daftar yang dipulangkan
        selalu berisi baris dengan sasaran identik — sama dengan satu
        keranjang di `visible_employees_q()`, dan itulah yang membuat
        kedua jalur tetap sepakat.
        """
        organization = getattr(employee, "organization", None)
        employment = getattr(employee, "employment", None)

        company_id = getattr(organization, "company_id", None)
        location_id = getattr(organization, "location_id", None)
        group_id = getattr(employment, "employee_group_id", None)

        candidates = (
            EmployeeDataPolicy.objects
            .filter(
                subject=subject,
                is_deleted=False,
                is_active=True,
            )
            .select_related("role")
        )

        matched = [
            policy
            for policy in candidates
            # Aturan yang menyebut sasaran tertentu hanya berlaku untuk
            # sasaran itu; yang mengosongkannya berlaku untuk semua.
            if (not policy.company_id or policy.company_id == company_id)
            and (not policy.location_id or policy.location_id == location_id)
            and (
                not policy.employee_group_id
                or policy.employee_group_id == group_id
            )
        ]

        if not matched:
            return []

        top = max(policy.specificity for policy in matched)

        return [policy for policy in matched if policy.specificity == top]

    # ------------------------------------------------------------------
    # Putusan
    # ------------------------------------------------------------------

    @classmethod
    def can_view(cls, *, employee, subject: str, user) -> bool:
        """
        Boleh atau tidak `user` melihat kelompok `subject` milik
        `employee`.
        """
        if user is None or not getattr(user, "is_authenticated", False):
            return False

        # Superuser dilewati, sama seperti di engine workflow dan
        # `EmployeeActionPolicy`. Tanpa itu satu aturan yang salah isi
        # mengunci datanya tanpa jalan keluar selain lewat shell.
        if user.is_superuser:
            return True

        policies = cls.matches(employee=employee, subject=subject)

        # Tidak ada aturan sama sekali = terlihat. Konsisten dengan
        # seluruh sistem ini (role tanpa baris menu = tanpa batasan);
        # tenant yang belum mengatur apa pun tidak mendadak kehilangan
        # tab History. Keamanannya datang dari seed bawaan, yang
        # barisnya terlihat dan bisa diubah di layar setting — bukan
        # dari aturan yang tertanam di kode.
        if not policies:
            return True

        viewer = cls._employee_of(user)

        # Sekali, di luar loop: baris kedua untuk sasaran yang sama
        # jangan sampai berarti query kedua.
        role_ids = set(
            user.roles.filter(is_deleted=False).values_list("id", flat=True)
        )

        # Cukup **satu** baris yang membolehkan. Baris di tingkat yang
        # sama menambah, tidak saling membatalkan — kalau tidak, aturan
        # "Finance Manager juga boleh" justru mencabut hak HR Manager
        # yang sudah ada, dan pencabutannya tidak berbunyi di mana pun.
        for policy in policies:
            if (
                policy.allow_self
                and viewer is not None
                and viewer.pk == employee.pk
            ):
                return True

            if policy.allow_manager and cls._is_manager(
                employee=employee,
                viewer=viewer,
                levels=policy.manager_levels or 1,
            ):
                return True

            if policy.allow_department_head and cls._is_department_head(
                employee=employee,
                viewer=viewer,
            ):
                return True

            if policy.role_id and policy.role_id in role_ids:
                return True

        return False

    @classmethod
    def hidden_action_types(cls, *, employee, user) -> set[str]:
        """
        Jenis `EmployeeAction` yang harus dibuang dari riwayat.

        Dikembalikan sebagai himpunan jenis, bukan daftar kelompok,
        supaya pemanggilnya tidak perlu tahu pemetaannya — dan
        pemetaan itu tetap satu tempat.
        """
        from apps.administration.models import SUBJECT_ACTION_TYPES

        hidden: set[str] = set()

        for subject, action_types in SUBJECT_ACTION_TYPES.items():
            if not cls.can_view(
                employee=employee,
                subject=str(subject),
                user=user,
            ):
                hidden.update(action_types)

        return hidden

    @classmethod
    def hidden_employee_fields(cls, *, employee, user) -> set[str]:
        """Field `EmployeeSerializer` yang harus dibuang dari payload."""
        from apps.administration.models import SUBJECT_EMPLOYEE_FIELDS

        hidden: set[str] = set()

        for subject, field_names in SUBJECT_EMPLOYEE_FIELDS.items():
            if not cls.can_view(
                employee=employee,
                subject=str(subject),
                user=user,
            ):
                hidden.update(field_names)

        return hidden

    # ------------------------------------------------------------------
    # Penyaringan queryset
    # ------------------------------------------------------------------

    @classmethod
    def visible_employees_q(cls, *, subject: str, user):
        """
        `Q` untuk queryset `Employee`: baris mana yang kelompok
        `subject`-nya boleh dilihat `user`. `None` = tanpa batasan.

        Dibangun sebagai Q, bukan dinilai baris per baris di Python,
        karena pemakainya endpoint berpaginasi — menyaring hasil
        halaman membuat `count` berbeda dari isinya, dan halaman
        terakhir bisa kosong tanpa sebab yang terlihat.
        """
        from django.db.models import Q

        from apps.administration.models import EmployeeDataPolicy

        if user is None or not getattr(user, "is_authenticated", False):
            return Q(pk__in=[])

        if user.is_superuser:
            return None

        policies = list(
            EmployeeDataPolicy.objects
            .filter(subject=subject, is_deleted=False, is_active=True)
            .select_related("role")
        )

        if not policies:
            return None

        viewer = cls._employee_of(user)

        role_ids = set(
            user.roles.filter(is_deleted=False).values_list("id", flat=True)
        )

        allowed = Q(pk__in=[])

        # Cakupan yang sudah diatur baris sebelumnya. **`Q()` kosong
        # tidak bisa dipakai menampungnya**: di Django `Q()` berarti
        # "tanpa filter", jadi `Q() | Q()` tetap kosong dan `~Q()` tidak
        # menyaring apa pun. Aturan global — yang justru paling lazim —
        # punya cakupan kosong, sehingga versi pertama fungsi ini
        # menghasilkan `Q` yang membuang seluruh baris untuk orang yang
        # seharusnya boleh melihat. Karena itu "berlaku untuk semua"
        # disimpan sebagai penanda tersendiri, bukan sebagai `Q` kosong.
        prior_scopes: list = []
        prior_covers_all = False

        # Dikelompokkan menurut **sasarannya**, bukan dinilai baris per
        # baris. Ini inti perubahan Stage 3A.1.
        #
        # Sebelumnya baris diproses satu per satu dan yang pertama
        # "berlaku untuk semua" menyetel `prior_covers_all` lalu
        # `break` — sehingga baris global **kedua** tidak pernah
        # dinilai. Dua baris global untuk satu kelompok karena itu
        # tidak berarti "dua role boleh", melainkan "role di baris
        # pertama boleh, baris kedua tidak berlaku", tanpa satu pesan
        # pun. Itu yang memblokir 3A-7 dan 3A-8.
        #
        # Yang **tidak** ikut berubah: baris yang lebih khusus tetap
        # menutupi yang lebih umum (`~earlier` di bawah). Itu satu-
        # satunya bentuk "tidak boleh" yang dipunyai master ini — baris
        # `company=A, role=HR-ADMIN-A` memang dimaksudkan mencabut
        # jangkauan baris global di Company A. Menyatukan semuanya
        # dengan OR akan mengubah setiap pencabutan itu jadi izin.
        #
        # Jadi: **OR di dalam sasaran yang sama, menutupi antar
        # sasaran.** Satu sasaran = satu keranjang.
        buckets: dict[tuple, list] = {}

        for policy in policies:
            key = (
                policy.company_id,
                policy.location_id,
                policy.employee_group_id,
            )

            buckets.setdefault(key, []).append(policy)

        def rank(key: tuple) -> tuple:
            company_id, location_id, group_id = key

            # Bobot yang sama dengan `EmployeeDataPolicy.specificity`.
            # Tiebreaker-nya id, supaya urutan dua sasaran sepadan
            # (Company A vs Company B) tidak bergantung pada urutan
            # baris di database — `None` diganti 0 karena `None` tidak
            # bisa dibandingkan dengan int.
            score = (
                (4 if company_id else 0)
                + (2 if location_id else 0)
                + (1 if group_id else 0)
            )

            return (score, tuple(value or 0 for value in key))

        # Dari yang paling khusus ke yang paling umum: pegawai yang
        # sudah diatur sasaran lebih khusus tidak boleh dinilai ulang
        # oleh sasaran global. Ini versi SQL dari tingkat teratas di
        # `matches()`, dan keduanya harus tetap sepakat — kalau
        # berbeda, tabel dan kartu memperlihatkan himpunan yang
        # berlainan.
        #
        # Tidak ada lagi `break`: hanya sasaran `(None, None, None)`
        # yang "berlaku untuk semua", ia satu-satunya di skor 0, dan
        # karena itu selalu keranjang terakhir. `prior_covers_all`
        # tinggal dipakai untuk memutuskan ekor fungsi ini.
        for key in sorted(buckets, key=rank, reverse=True):
            company_id, location_id, group_id = key

            scope = Q()
            covers_all = True

            if company_id:
                scope &= Q(organization__company_id=company_id)
                covers_all = False

            if location_id:
                scope &= Q(organization__location_id=location_id)
                covers_all = False

            if group_id:
                scope &= Q(employment__employee_group_id=group_id)
                covers_all = False

            here = scope

            for earlier in prior_scopes:
                here &= ~earlier

            # Gabungan seluruh baris di sasaran ini. `None` = baris itu
            # tidak membolehkan siapa pun; ia dilewati, bukan membuat
            # keranjangnya kosong.
            permitted = None

            for policy in buckets[key]:
                one = cls._permission_q(
                    policy=policy,
                    user=user,
                    viewer=viewer,
                    role_ids=role_ids,
                )

                if one is None:
                    continue

                permitted = one if permitted is None else permitted | one

            if permitted is not None:
                allowed |= here & permitted

            if covers_all:
                prior_covers_all = True
            else:
                prior_scopes.append(scope)

        # Pegawai yang tidak diatur baris mana pun tetap terlihat —
        # "tanpa aturan = terlihat", sama seperti di `can_view`.
        if prior_covers_all:
            return allowed

        ungoverned = Q()

        for earlier in prior_scopes:
            ungoverned &= ~earlier

        return allowed | ungoverned

    @classmethod
    def _permission_q(cls, *, policy, user, viewer, role_ids):
        """
        Syarat "boleh melihat" untuk satu aturan, sebagai `Q` terhadap
        `Employee`. `None` kalau tidak seorang pun memenuhinya.
        """
        from django.db.models import Q

        # Role berlaku menyeluruh: kalau viewer memegangnya, aturan ini
        # tidak menyaring satu baris pun.
        #
        # `Q(pk__isnull=False)`, **bukan** `Q()`: yang kedua berarti
        # "tanpa filter" di Django, dan `Q(pk__in=[]) | Q()` justru
        # mengembalikan `Q(pk__in=[])` — jadi pemegang role kehilangan
        # semua barisnya, kebalikan dari yang dimaksud. Jebakan yang
        # sama dengan cakupan kosong di `visible_employees_q`.
        if policy.role_id and policy.role_id in role_ids:
            return Q(pk__isnull=False)

        conditions = Q(pk__in=[])
        matched = False

        if policy.allow_self:
            conditions |= Q(user_id=user.pk)
            matched = True

        if policy.allow_manager and viewer is not None:
            path = "organization__reports_to"

            for _ in range(max(int(policy.manager_levels or 1), 1)):
                conditions |= Q(**{f"{path}_id": viewer.pk})

                path = f"{path}__organization__reports_to"

            matched = True

        if policy.allow_department_head and viewer is not None:
            viewer_org = getattr(viewer, "organization", None)
            position = getattr(viewer_org, "position", None)

            if getattr(position, "is_manager", False) and viewer_org.department_id:
                conditions |= Q(
                    organization__department_id=viewer_org.department_id,
                )

                matched = True

        return conditions if matched else None

    @classmethod
    def can_view_action(cls, *, employee, action_type: str, user) -> bool:
        """Satu jenis action, untuk pemanggil yang cuma punya satu baris."""
        subject = subject_for_action(action_type)

        # Jenis yang tidak masuk kelompok mana pun tidak bisa dibatasi.
        # Itu keadaan yang sah untuk jenis baru yang belum dipetakan —
        # dan `SUBJECT_ACTION_TYPES` yang harus diperbarui, bukan di
        # sini.
        if subject is None:
            return True

        return cls.can_view(employee=employee, subject=subject, user=user)

    # ------------------------------------------------------------------
    # Relasi orang
    # ------------------------------------------------------------------

    @staticmethod
    def _employee_of(user):
        """
        Pegawai milik sebuah akun.

        Accessor-nya `employee_profile` — `Employee.user` sebuah
        `OneToOneField` dengan `related_name` itu. Sempat ditulis
        `user.employee`, dan kegagalannya ke arah yang paling
        berbahaya: `getattr` mengembalikan `None` tanpa error, jadi
        "pegawainya sendiri" dan "atasan langsung" **tidak pernah**
        cocok — riwayat gajinya sendiri pun tertutup untuknya, dan
        tidak ada satu pun pesan yang menyebutkannya.

        `RelatedObjectDoesNotExist` untuk akun yang bukan pegawai
        (admin sistem) ditangkap `getattr` dengan bawaan `None`.
        """
        return getattr(user, "employee_profile", None)

    @staticmethod
    def _is_manager(*, employee, viewer, levels: int) -> bool:
        """
        Apakah `viewer` ada di garis pelaporan `employee`, sampai
        `levels` tingkat ke atas.

        Ditelusuri lewat `OrganizationAssignment.reports_to`, dengan
        pagar terhadap garis pelaporan yang berputar — data yang
        melingkar bukan hal mustahil di master yang diisi tangan, dan
        kalau terjadi, satu request menggantung selamanya.
        """
        if viewer is None:
            return False

        current = employee
        seen = {employee.pk}

        for _ in range(max(int(levels), 1)):
            organization = getattr(current, "organization", None)

            manager = getattr(organization, "reports_to", None)

            if manager is None:
                return False

            if manager.pk == viewer.pk:
                return True

            if manager.pk in seen:
                return False

            seen.add(manager.pk)
            current = manager

        return False

    @staticmethod
    def _is_department_head(*, employee, viewer) -> bool:
        """
        Pemegang jabatan bertanda Manager di department pegawainya.

        Aturannya sama persis dengan `ApproverType.DEPARTMENT_HEAD` di
        engine workflow dan `ActionInitiator.DEPARTMENT_HEAD` — kalau
        berbeda, orang yang boleh membaca riwayat dan orang yang
        menandatangani perubahannya bisa dua orang yang berlainan tanpa
        ada yang menyadarinya.
        """
        if viewer is None:
            return False

        organization = getattr(employee, "organization", None)
        department_id = getattr(organization, "department_id", None)

        if department_id is None:
            return False

        viewer_org = getattr(viewer, "organization", None)

        if viewer_org is None or viewer_org.department_id != department_id:
            return False

        position = getattr(viewer_org, "position", None)

        return bool(getattr(position, "is_manager", False))


class EmployeeDataSubjectMixin:
    """
    Menyaring baris sub-resource kartu pegawai lewat `EmployeeDataPolicy`.

    Tab Payroll, Bank Accounts, Family, Medical, dan Documents bukan
    field di `EmployeeSerializer` — masing-masing endpoint tersendiri.
    Jadi menutup kartu pegawai saja tidak menutup apa pun: angkanya
    tetap terbaca lewat `/api/hr/payroll-assignments/?employee=<id>`,
    dan itu justru URL yang dipakai tabnya sendiri.

    Dipasang di `filter_queryset()`, **bukan** `get_queryset()`, dengan
    alasan yang sama seperti `DataScopeService`: `get_object()` DRF
    memanggil `filter_queryset(get_queryset())`, jadi satu tempat ini
    menutup daftar, detail by id, export, bulk-delete, dan update
    sekaligus — sementara puluhan viewset menimpa `get_queryset()`
    sendiri dan akan lolos diam-diam.
    """

    # Kelompok `EmployeeDataSubject` yang mengatur resource ini.
    data_subject: str | None = None

    # Jalur ORM dari model resource ke Employee.
    data_subject_path: str = "employee"

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)

        if not self.data_subject:
            return queryset

        user = getattr(self.request, "user", None)

        allowed = EmployeeDataVisibility.visible_employees_q(
            subject=str(self.data_subject),
            user=user,
        )

        if allowed is None:
            return queryset

        from apps.hr.models import Employee

        return queryset.filter(**{
            f"{self.data_subject_path}__in": Employee.objects.filter(allowed),
        })
