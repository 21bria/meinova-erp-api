"""
Resolusi kalender kerja dan hari libur — **satu tempat**.

Sebelum ini, urutan pencariannya tinggal di `LeaveDayCalculator` dan
dipanggil ulang oleh Attendance, Payroll, Reports, dan Shift Calendar.
Itu masih benar selama tidak ada yang menyalinnya; begitu cakupan
GLOBAL masuk, siapa pun yang menulis versi keduanya akan menghasilkan
hari kerja yang berbeda untuk pegawai yang sama, dan selisihnya baru
terbaca di slip gaji.

Karena itu resolver-nya dipisah ke sini dan `LeaveDayCalculator`
mendelegasikan kepadanya. Yang butuh kalender memanggil salah satu dari
dua fungsi di bawah — **jangan** menulis query `WorkCalendar` atau
`Holiday` sendiri di modul konsumen.

Presedennya, dari yang paling spesifik:

    EMPLOYEE OVERRIDE   EmploymentAssignment.working_calendar
      ↓
    LOCATION            scope=LOCATION, company + location cocok
      ↓
    COMPANY             scope=COMPANY, company cocok
      ↓
    GLOBAL              scope=GLOBAL
      ↓
    (tidak ada)         pemanggil yang memutuskan fallback-nya

Hari libur **tidak** berpreseden: cakupannya digabung, bukan dipilih.
Libur nasional tetap berlaku di site yang juga punya libur lokalnya
sendiri — mengambil "yang paling spesifik saja" akan menghapus 17
Agustus dari lokasi yang kebetulan punya Safety Day.
"""

from __future__ import annotations

from datetime import date

from django.db.models import Q

from apps.administration.models.calendar import (
    CalendarScope,
    Holiday,
    HolidayScope,
    HolidaySyncStatus,
    WorkCalendar,
)


class CalendarResolver:
    """Classmethod-only, tanpa keadaan."""

    # ------------------------------------------------------------------
    # Work Calendar
    # ------------------------------------------------------------------

    @classmethod
    def base_calendar_queryset(cls):
        return WorkCalendar.objects.filter(
            is_deleted=False,
            is_active=True,
        )

    @classmethod
    def resolve_work_calendar(
        cls,
        *,
        company_id: int | None,
        location_id: int | None = None,
        override=None,
    ) -> WorkCalendar | None:
        """
        Kalender yang berlaku untuk satu penempatan organisasi.

        `override` adalah kalender yang sudah ditempelkan langsung ke
        pegawai (`EmploymentAssignment.working_calendar`). Ia menang
        atas segalanya — itu arti "override" — dan dikembalikan apa
        adanya tanpa satu query pun.

        Mengembalikan None kalau tidak ada satu pun yang cocok. Fallback
        "Senin–Jumat" **tidak** diputuskan di sini: yang tahu apa artinya
        tidak punya kalender adalah pemanggilnya, dan menanamnya di sini
        membuat kode pemanggil tidak bisa membedakan "tidak ada
        kalender" dari "kalendernya kebetulan Senin–Jumat".
        """
        if override is not None:
            return override

        queryset = cls.base_calendar_queryset()

        # LOCATION lebih dulu, dan hanya kalau penempatannya memang
        # menyebut lokasi. Site yang tidak punya kalender sendiri
        # jatuh ke company-nya, lalu ke GLOBAL — itu yang membuat
        # "cukup ikut GLOBAL" tidak perlu baris apa pun.
        if location_id and company_id:
            calendar = (
                queryset
                .filter(
                    scope=CalendarScope.LOCATION,
                    company_id=company_id,
                    location_id=location_id,
                )
                .order_by("-is_default", "id")
                .first()
            )

            if calendar is not None:
                return calendar

        if company_id:
            calendar = (
                queryset
                .filter(
                    scope=CalendarScope.COMPANY,
                    company_id=company_id,
                )
                .order_by("-is_default", "id")
                .first()
            )

            if calendar is not None:
                return calendar

        return (
            queryset
            .filter(scope=CalendarScope.GLOBAL)
            .order_by("-is_default", "id")
            .first()
        )

    @classmethod
    def resolve_for_employee(cls, employee) -> WorkCalendar | None:
        """Bentuk yang dipakai modul HR: langsung dari objek pegawai."""
        employment = getattr(employee, "employment", None)
        organization = getattr(employee, "organization", None)

        override = None

        if employment is not None and employment.working_calendar_id:
            override = employment.working_calendar

        return cls.resolve_work_calendar(
            company_id=getattr(organization, "company_id", None),
            location_id=getattr(organization, "location_id", None),
            override=override,
        )

    # ------------------------------------------------------------------
    # Holiday
    # ------------------------------------------------------------------

    @classmethod
    def holiday_scope_filter(
        cls,
        *,
        company_id: int | None,
        location_id: int | None = None,
    ) -> Q:
        """
        Syarat cakupan hari libur untuk satu penempatan organisasi.

        Dipisah dari `resolve_holidays()` supaya layar daftar dan
        laporan bisa memakai syarat yang **sama persis** tanpa menyalin
        empat cabang di bawah. Empat cabang yang tercecer di empat modul
        adalah empat kesempatan salah satunya ketinggalan diperbarui.
        """
        # GLOBAL selalu ikut, termasuk untuk pegawai yang penempatannya
        # belum lengkap. Perusahaan yang dibuat hari ini mendapatkannya
        # tanpa import ulang apa pun — tidak ada daftar yang perlu
        # disusul.
        condition = Q(scope=HolidayScope.GLOBAL)

        if not company_id:
            return condition

        condition |= Q(
            scope=HolidayScope.COMPANY,
            company_id=company_id,
        )

        condition |= Q(
            scope=HolidayScope.SELECTED_COMPANIES,
            companies__company_id=company_id,
            companies__is_deleted=False,
        )

        if location_id:
            condition |= Q(
                scope=HolidayScope.LOCATION,
                company_id=company_id,
                location_id=location_id,
            )

        return condition

    @classmethod
    def base_holiday_queryset(cls):
        return Holiday.objects.filter(
            is_deleted=False,
            is_active=True,
            # Baris hasil sync yang belum ditinjau tersimpan, tapi
            # tidak berlaku. Ini gerbang antara sumber luar dan
            # kalender yang menggerakkan payroll — lihat
            # `HolidaySyncStatus`.
            sync_status=HolidaySyncStatus.CONFIRMED,
        )

    @classmethod
    def resolve_holidays(
        cls,
        *,
        company_id: int | None,
        location_id: int | None,
        start: date,
        end: date,
    ) -> set[date]:
        queryset = (
            cls.base_holiday_queryset()
            .filter(date__gte=start, date__lte=end)
            .filter(
                cls.holiday_scope_filter(
                    company_id=company_id,
                    location_id=location_id,
                ),
            )
        )

        # `distinct()` bukan hiasan: cabang SELECTED_COMPANIES adalah
        # join ke tabel relasi, jadi satu hari libur yang menyebut satu
        # perusahaan dua kali akan terbaca dua baris. Hasilnya `set`,
        # jadi tidak terlihat di sini — tapi ikut membengkakkan query
        # yang sama dipakai layar daftar.
        return set(
            queryset
            .values_list("date", flat=True)
            .distinct(),
        )

    @classmethod
    def resolve_holidays_for_employee(
        cls,
        employee,
        start: date,
        end: date,
    ) -> set[date]:
        organization = getattr(employee, "organization", None)

        return cls.resolve_holidays(
            company_id=getattr(organization, "company_id", None),
            location_id=getattr(organization, "location_id", None),
            start=start,
            end=end,
        )


# ======================================================================
# VISIBILITAS (RBAC)
# ======================================================================


def scope_holidays_for_user(queryset, user):
    """
    Menyaring queryset `Holiday` menurut cakupan data pembacanya.

    Dipisah ke sini — bukan ditulis di viewset — karena **tiga** tempat
    membaca daftar hari libur atas nama seseorang: layar Holiday,
    sorotan dashboard HR, dan widget Upcoming Holidays di Overview.
    Tiga salinan aturan yang harus tetap sepakat adalah tiga kesempatan
    salah satunya ketinggalan diperbarui, dan yang ketinggalan di sini
    bocor lintas perusahaan.

    Dua hal yang harus berlaku bersamaan:

    * `allow_null=True` supaya baris **GLOBAL** (`company IS NULL`)
      tetap terlihat. Bawaan `DATA_SCOPE_INCLUDE_NULL` adalah False,
      jadi tanpa ini justru libur nasional yang hilang dari layar
      setiap admin site.
    * `SELECTED_COMPANIES` **tidak** ikut dilonggarkan. Cakupan itu juga
      menyimpan `company = NULL` — daftarnya di tabel relasi — jadi
      kelonggaran yang benar untuk GLOBAL meloloskannya juga, padahal
      daftarnya bisa tidak memuat perusahaan pembacanya sama sekali.
    """
    from apps.accounts.scoping import DataScopeService
    from apps.administration.models import Company

    queryset = DataScopeService.filter(
        queryset,
        {"company": "company", "location": "location"},
        user,
        allow_null=True,
    )

    scope = DataScopeService.for_user(user)

    if scope.unrestricted:
        return queryset

    # Perusahaan yang boleh dilihat orang ini, dihitung dengan menyaring
    # Company memakai id-nya sendiri. Lewat `DataScopeService` lagi —
    # bukan membaca `role_scopes` langsung — supaya mode `placement` dan
    # gabungan antar-penugasan ikut terhitung tanpa disalin ulang di
    # sini.
    allowed_companies = DataScopeService.filter(
        Company.objects.filter(is_deleted=False),
        {"company": "id"},
        user,
    )

    visible_selected = queryset.filter(
        scope=HolidayScope.SELECTED_COMPANIES,
        companies__company__in=allowed_companies,
        companies__is_deleted=False,
    )

    return (
        queryset.exclude(scope=HolidayScope.SELECTED_COMPANIES)
        | visible_selected
    ).distinct()
