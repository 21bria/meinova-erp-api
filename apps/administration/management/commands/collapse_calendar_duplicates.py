"""
Menggabungkan Work Calendar dan Holiday yang terduplikasi per company.

    python manage.py tenant_command collapse_calendar_duplicates \\
        --schema=demo [--apply]

**Dry-run adalah bawaannya.** Tanpa `--apply` tidak satu baris pun
disentuh; yang keluar cuma laporan apa yang akan terjadi. Ini bukan
kehati-hatian berlebihan: perintah ini mengubah kalender yang
menentukan hari kerja, dan lewat hari kerja menentukan potongan cuti,
absen, dan prorata gaji. Selisih yang lolos di sini baru terbaca di
slip gaji.

Yang digabungkan hanya yang **benar-benar identik pada seluruh field
yang berpengaruh**. Dua baris yang kodenya sama tapi hari kerjanya
berbeda — atau namanya menyebut lokasi yang berbeda — dilaporkan
sebagai exception dan **tidak** disentuh. Kesamaan nama atau kode saja
tidak pernah cukup.

Urutan yang dijaga:

1. baris penyimpan (keeper) dipilih dan cakupannya dinaikkan;
2. **seluruh FK dipindahkan ke keeper** sebelum apa pun dihapus;
3. sisanya di-soft delete, bukan dihapus permanen.

Langkah 2 yang membuat ini aman dijalankan di tenant yang sudah
berjalan: `EmploymentAssignment.working_calendar` memakai `PROTECT`,
jadi urutan yang terbalik akan berhenti di tengah dengan sebagian
kalender sudah dinaikkan dan sebagian belum.
"""

from __future__ import annotations

from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.administration.models import (
    CalendarScope,
    Company,
    Holiday,
    HolidayCompany,
    HolidayScope,
    WorkCalendar,
)


# Field yang menentukan **perilaku** kalender. Dua baris yang sama di
# seluruh field ini menghasilkan hari kerja yang sama untuk siapa pun,
# jadi menggabungkannya tidak mengubah jawaban apa pun.
#
# `is_default` ikut: kalender default company dan yang bukan
# diperlakukan berbeda oleh resolver saat satu company punya lebih dari
# satu kalender.
WORK_CALENDAR_IDENTITY = (
    "code",
    "name",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "is_default",
    "is_active",
)

HOLIDAY_IDENTITY = (
    "code",
    "name",
    "date",
    "country_code",
    "is_national",
    "is_recurring",
    "is_active",
)


class Command(BaseCommand):
    help = (
        "Collapse per-company duplicate Work Calendars and Holidays "
        "into GLOBAL / SELECTED_COMPANIES scope."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help=(
                "Benar-benar menulis perubahannya. Tanpa ini perintah "
                "hanya melaporkan."
            ),
        )

        parser.add_argument(
            "--only",
            choices=["work-calendar", "holiday"],
            help="Batasi ke satu resource saja.",
        )

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        self.apply = options["apply"]
        self.only = options.get("only")

        self.company_ids = set(
            Company.objects
            .filter(is_deleted=False, is_active=True)
            .values_list("id", flat=True)
        )

        if not self.company_ids:
            self.stdout.write(
                self.style.WARNING(
                    "Tenant ini tidak punya company aktif — tidak ada "
                    "yang bisa dibandingkan.",
                )
            )

            return

        self.stdout.write(
            f"Company aktif: {len(self.company_ids)}\n"
            f"Mode: {'APPLY' if self.apply else 'DRY-RUN'}\n"
        )

        with transaction.atomic():
            if self.only != "holiday":
                self.collapse_work_calendars()

            if self.only != "work-calendar":
                self.collapse_holidays()

            if not self.apply:
                # Dry-run tetap menjalankan seluruh jalurnya, lalu
                # membatalkannya. Itu yang membuat laporannya bisa
                # dipercaya: yang dilaporkan adalah yang benar-benar
                # terjadi, bukan simulasi yang ditulis terpisah dan
                # bisa menyimpang dari kode yang menulis.
                transaction.set_rollback(True)

    # ------------------------------------------------------------------
    # Work Calendar
    # ------------------------------------------------------------------

    def collapse_work_calendars(self):
        self.stdout.write(self.style.MIGRATE_HEADING("\nWork Calendar"))

        rows = list(
            WorkCalendar.objects
            .filter(
                is_deleted=False,
                scope=CalendarScope.COMPANY,
                location__isnull=True,
                company__isnull=False,
            )
            .order_by("id")
        )

        groups = self._group(rows, WORK_CALENDAR_IDENTITY)

        exceptions = self._exceptions_by_code(rows, WORK_CALENDAR_IDENTITY)

        collapsed = 0

        for key, members in groups.items():
            if len(members) < 2:
                continue

            code = dict(zip(WORK_CALENDAR_IDENTITY, key))["code"]

            covered = {row.company_id for row in members}

            if covered != self.company_ids:
                # Sebagian perusahaan saja. Menaikkannya jadi GLOBAL
                # akan memberi kalender ini kepada perusahaan yang
                # selama ini **tidak** memilikinya — hari kerja mereka
                # berubah tanpa ada yang memintanya. Work Calendar
                # tidak punya cakupan "sebagian", jadi ini dilaporkan
                # dan dibiarkan.
                self.stdout.write(
                    self.style.WARNING(
                        f"  SKIP  {code}: {len(members)} baris identik "
                        f"tapi cuma mencakup {len(covered)} dari "
                        f"{len(self.company_ids)} company. Naikkan "
                        f"manual kalau memang dimaksudkan GLOBAL."
                    )
                )

                continue

            # Kembaran GLOBAL yang sudah ada lebih dulu.
            #
            # Ini jalur yang lazim, bukan kasus pinggiran: tenant lama
            # menjalankan seed baru (yang menerbitkan `HO-STANDARD`
            # GLOBAL) lalu menjalankan perintah ini. Tanpa pemeriksaan
            # ini, mempromosikan keeper ke GLOBAL menabrak
            # `uniq_active_work_calendar_scope_code` dan perintahnya
            # berhenti di tengah — sebagian grup sudah digabung,
            # sebagian belum.
            twin = (
                WorkCalendar.objects
                .filter(
                    is_deleted=False,
                    scope=CalendarScope.GLOBAL,
                    company__isnull=True,
                    location__isnull=True,
                    code=code,
                )
                .exclude(pk__in=[row.pk for row in members])
                .first()
            )

            if twin is not None:
                # Yang GLOBAL sudah ada: seluruh duplikat diarahkan ke
                # sana, tidak ada yang dipromosikan.
                self.stdout.write(
                    f"  ADOPT {code}: {len(members)} baris → GLOBAL yang "
                    f"sudah ada (id={twin.id})"
                )

                if self.apply:
                    self._repoint_work_calendar(twin, members)
                    self._soft_delete(members)

                collapsed += 1

                continue

            keeper = members[0]
            others = members[1:]

            self.stdout.write(
                f"  MERGE {code}: {len(members)} baris → 1 GLOBAL "
                f"(keeper id={keeper.id})"
            )

            # Dua peringatan yang keduanya soal **resolusi berubah diam-
            # diam**, dan keduanya ditemukan saat UAT — bukan saat
            # menulis kodenya.
            #
            # 1. Kalender GLOBAL bawaan yang sudah ada. Resolver
            #    mengurutkan `-is_default, id`, jadi dua baris GLOBAL
            #    yang sama-sama default tetap menghasilkan jawaban
            #    tunggal — tapi jawabannya ditentukan nomor urut, dan
            #    tidak ada layar yang menjelaskan itu kepada yang
            #    membacanya.
            if keeper.is_default:
                rival = (
                    WorkCalendar.objects
                    .filter(
                        is_deleted=False,
                        scope=CalendarScope.GLOBAL,
                        is_default=True,
                    )
                    .exclude(pk__in=[row.pk for row in members])
                    .first()
                )

                if rival is not None:
                    self.stdout.write(
                        self.style.WARNING(
                            f"        PERIKSA: sudah ada kalender GLOBAL "
                            f"bawaan '{rival.code}'. Setelah digabung ada "
                            f"dua, dan yang menang ditentukan id terkecil "
                            f"— matikan salah satu is_default."
                        )
                    )

            # 2. Company yang masih punya kalender COMPANY lain.
            #    Menaikkan yang ini ke GLOBAL membuat kalender yang
            #    tersisa itu **menang** atasnya — hari kerja perusahaan
            #    tersebut berubah tanpa satu baris pun disunting.
            leftovers = (
                WorkCalendar.objects
                .filter(
                    is_deleted=False,
                    scope=CalendarScope.COMPANY,
                    company_id__in=covered,
                )
                .exclude(pk__in=[row.pk for row in members])
                .values_list("company__code", "code")
            )

            for company_code, other_code in leftovers:
                self.stdout.write(
                    self.style.WARNING(
                        f"        PERIKSA: {company_code} masih punya "
                        f"'{other_code}' bercakupan COMPANY — sesudah "
                        f"digabung, itulah yang berlaku untuk "
                        f"{company_code}, bukan '{code}'."
                    )
                )

            if self.apply:
                self._repoint_work_calendar(keeper, others)

                keeper.scope = CalendarScope.GLOBAL
                keeper.company = None
                keeper.location = None
                keeper.save(
                    update_fields=["scope", "company", "location", "updated_at"],
                )

                self._soft_delete(others)

            collapsed += 1

        self._report_exceptions(exceptions)

        self.stdout.write(f"  → {collapsed} grup digabungkan.")

    def _repoint_work_calendar(self, keeper, others):
        """
        Memindahkan seluruh referensi ke keeper **sebelum** yang lain
        dihapus.

        `EmploymentAssignment.working_calendar` memakai `PROTECT`, jadi
        ini bukan kerapian — tanpa ini perintahnya berhenti di tengah.
        """
        from apps.hr.models import EmploymentAssignment

        other_ids = [row.id for row in others]

        moved = (
            EmploymentAssignment.objects
            .filter(working_calendar_id__in=other_ids)
            .update(working_calendar=keeper)
        )

        if moved:
            self.stdout.write(
                f"        {moved} employment assignment dipindah ke "
                f"keeper."
            )

    # ------------------------------------------------------------------
    # Holiday
    # ------------------------------------------------------------------

    def collapse_holidays(self):
        self.stdout.write(self.style.MIGRATE_HEADING("\nHoliday"))

        rows = list(
            Holiday.objects
            .filter(
                is_deleted=False,
                scope=HolidayScope.COMPANY,
                location__isnull=True,
                company__isnull=False,
            )
            .order_by("id")
        )

        groups = self._group(rows, HOLIDAY_IDENTITY)

        exceptions = self._exceptions_by_code(rows, HOLIDAY_IDENTITY)

        collapsed = 0

        for key, members in groups.items():
            if len(members) < 2:
                continue

            fields = dict(zip(HOLIDAY_IDENTITY, key))

            code = fields["code"]

            covered = {row.company_id for row in members}

            # Kembaran GLOBAL yang sudah ada — lihat alasannya di
            # `collapse_work_calendars()`. Kunci bisnis hari libur ikut
            # menyertakan tanggalnya.
            twin = (
                Holiday.objects
                .filter(
                    is_deleted=False,
                    scope=HolidayScope.GLOBAL,
                    company__isnull=True,
                    location__isnull=True,
                    date=fields["date"],
                    code=code,
                )
                .exclude(pk__in=[row.pk for row in members])
                .first()
            )

            if twin is not None:
                self.stdout.write(
                    f"  ADOPT {code} {fields['date']}: {len(members)} "
                    f"baris → GLOBAL yang sudah ada (id={twin.id})"
                )

                if self.apply:
                    self._soft_delete(members)

                collapsed += 1

                continue

            keeper = members[0]
            others = members[1:]

            if covered == self.company_ids:
                target_scope = HolidayScope.GLOBAL

                label = "GLOBAL"
            else:
                # Sebagian perusahaan. Berbeda dengan Work Calendar,
                # Holiday memang punya cakupannya — barisnya jadi satu
                # dan daftar perusahaannya pindah ke `HolidayCompany`.
                target_scope = HolidayScope.SELECTED_COMPANIES

                label = f"SELECTED_COMPANIES ({len(covered)} company)"

            self.stdout.write(
                f"  MERGE {code} {fields['date']}: {len(members)} baris "
                f"→ 1 {label} (keeper id={keeper.id})"
            )

            if self.apply:
                if target_scope == HolidayScope.SELECTED_COMPANIES:
                    for company_id in sorted(covered):
                        HolidayCompany.objects.update_or_create(
                            holiday=keeper,
                            company_id=company_id,
                            defaults={"is_deleted": False},
                        )

                keeper.scope = target_scope
                keeper.company = None
                keeper.location = None
                keeper.save(
                    update_fields=["scope", "company", "location", "updated_at"],
                )

                self._soft_delete(others)

            collapsed += 1

        self._report_exceptions(exceptions)

        self.stdout.write(f"  → {collapsed} grup digabungkan.")

    # ------------------------------------------------------------------
    # Util
    # ------------------------------------------------------------------

    @staticmethod
    def _group(rows, identity_fields):
        groups: dict[tuple, list] = defaultdict(list)

        for row in rows:
            key = tuple(
                getattr(row, field_name)
                for field_name in identity_fields
            )

            groups[key].append(row)

        return groups

    @staticmethod
    def _exceptions_by_code(rows, identity_fields):
        """
        Baris yang **kodenya sama tapi isinya tidak**.

        Ini yang tidak boleh digabung diam-diam. Contoh nyata di tenant
        demo: `LOCATION-DAY-01-2026` ada di tiga perusahaan, tapi
        namanya menyebut lokasi yang berbeda-beda — tanggalnya
        kebetulan sama, peristiwanya tidak.
        """
        by_code: dict[str, set] = defaultdict(set)

        for row in rows:
            by_code[row.code].add(
                tuple(
                    getattr(row, field_name)
                    for field_name in identity_fields
                ),
            )

        return {
            code: variants
            for code, variants in by_code.items()
            if len(variants) > 1
        }

    def _report_exceptions(self, exceptions):
        for code, variants in sorted(exceptions.items()):
            self.stdout.write(
                self.style.ERROR(
                    f"  EXCEPTION {code}: {len(variants)} varian yang "
                    f"berbeda pada field berpengaruh — tidak digabung. "
                    f"Periksa manual."
                )
            )

    def _soft_delete(self, rows):
        now = timezone.now()

        for row in rows:
            row.is_deleted = True
            row.deleted_at = now
            row.save(
                update_fields=["is_deleted", "deleted_at", "updated_at"],
            )
