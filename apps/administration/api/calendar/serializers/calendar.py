from rest_framework import serializers

from apps.administration.models.calendar import validate_calendar_scope
from apps.administration.models import (
    Company,
    Holiday,
    HolidayCompany,
    HolidayScope,
    RosterCrew,
    WorkCalendar,
)


# Nama organisasi untuk kolom tabel.
#
# Generator memetakan kolom lookup ke `<field>_name`, jadi serializer
# yang cuma `fields = "__all__"` menghasilkan tabel yang kolom Company
# dan Location-nya "-" di **semua** baris — tanpa satu pun error.
#
# Akibatnya dulu jauh lebih buruk daripada sekadar kolom kosong: hari
# libur tersimpan satu baris per company, jadi layar Holiday menampilkan
# dua belas baris "New Year Holiday · 01-01-2026 · NEW-YEAR-2026" yang
# terlihat **persis sama**.
#
# Duplikasinya sendiri sudah hilang — libur nasional kini satu baris
# bercakupan GLOBAL. Yang menggantikan kedua kolom ini sebagai penjelas
# utama adalah `applies_to`: cakupan sebagai satu kalimat, dan **"All
# Companies"** untuk yang GLOBAL. Kolom Company yang kosong di sebelah
# baris yang justru berlaku paling luas terbaca seperti data yang lupa
# diisi.
class OrganizationNameMixin(serializers.Serializer):
    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    location_name = serializers.CharField(
        source="location.name",
        read_only=True,
        default=None,
    )



# Konsistensi cakupan, dijaga di lapis serializer.
#
# `Model.clean()` sudah memuat aturan yang sama, tapi DRF **tidak
# memanggilnya**: `ModelSerializer.save()` langsung ke `Model.save()`.
# Kedua Work Calendar dan Holiday menulis lewat jalur CRUD biasa (bukan
# `ServiceWriteMixin`), jadi tanpa mixin ini baris `scope=GLOBAL` yang
# masih menyebut company tersimpan lewat API — dan resolver akan
# membacanya sebagai baris yang berlaku untuk semua **dan** untuk satu
# perusahaan sekaligus.
class ScopeValidationMixin(serializers.Serializer):
    selected_scope: str | None = None

    def validate(self, attrs):
        attrs = super().validate(attrs)

        def current(name):
            if name in attrs:
                return attrs[name]

            return getattr(self.instance, name, None)

        location = current("location")

        errors = validate_calendar_scope(
            scope=current("scope"),
            company_id=getattr(current("company"), "id", None),
            location=location,
            location_id=getattr(location, "id", None),
            selected_scope=self.selected_scope,
        )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs


# Serializer Fiscal Year dan Posting Period pindah ke Finance.


class HolidaySerializer(
    ScopeValidationMixin,
    OrganizationNameMixin,
    serializers.ModelSerializer,
):
    selected_scope = HolidayScope.SELECTED_COMPANIES

    applies_to = serializers.CharField(read_only=True)

    # Daftar perusahaan untuk cakupan SELECTED_COMPANIES. Ditulis lewat
    # id, dibaca kembali lewat id — form generator memetakannya ke
    # multi-lookup, dan tabel tetap membaca `applies_to`.
    company_ids = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=Company.objects.filter(is_deleted=False),
        required=False,
        write_only=True,
    )

    selected_companies = serializers.SerializerMethodField()

    class Meta:
        model = Holiday
        fields = "__all__"

        read_only_fields = [
            "company_name",
            "location_name",
            "applies_to",
            "selected_companies",
            # Jejak asal-usul diisi mesin sync, bukan diketik orang.
            # Membiarkannya bisa ditulis lewat API berarti baris hasil
            # sync bisa dinyatakan CONFIRMED tanpa melewati layar
            # review — persis gerbang yang dipasang di
            # `HolidaySyncStatus`.
            "external_id",
            "source_url",
            "synced_at",
            "sync_status",
        ]

    def get_selected_companies(self, instance) -> list[int]:
        if instance.scope != HolidayScope.SELECTED_COMPANIES:
            return []

        return [
            row.company_id
            for row in instance.companies.all()
            if not row.is_deleted
        ]

    def validate(self, attrs):
        """
        Cakupan diperiksa di sini **dan** di `Model.clean()`.

        Bukan pengulangan yang sia-sia: yang di serializer menghasilkan
        error per field yang bisa ditempelkan form ke kolomnya, yang di
        model menjaga jalur yang tidak lewat API sama sekali (seed,
        shell, importer).
        """
        attrs = super().validate(attrs)

        scope = attrs.get(
            "scope",
            getattr(self.instance, "scope", None),
        )

        companies = attrs.get("company_ids")

        if scope == HolidayScope.SELECTED_COMPANIES:
            if companies is None and self.instance is None:
                raise serializers.ValidationError({
                    "company_ids": (
                        "Cakupan SELECTED_COMPANIES wajib menyebut "
                        "daftar perusahaan."
                    ),
                })

            if companies is not None and not companies:
                raise serializers.ValidationError({
                    "company_ids": (
                        "Daftar perusahaan tidak boleh kosong. Untuk "
                        "seluruh perusahaan, pakai cakupan GLOBAL."
                    ),
                })

        elif companies:
            raise serializers.ValidationError({
                "company_ids": (
                    "Daftar perusahaan hanya berlaku untuk cakupan "
                    "SELECTED_COMPANIES."
                ),
            })

        return attrs

    def create(self, validated_data):
        companies = validated_data.pop("company_ids", None)

        instance = super().create(validated_data)

        self._sync_companies(instance, companies)

        return instance

    def update(self, instance, validated_data):
        companies = validated_data.pop("company_ids", None)

        instance = super().update(instance, validated_data)

        self._sync_companies(instance, companies)

        return instance

    @staticmethod
    def _sync_companies(instance, companies):
        """
        `None` = tidak disebut permintaan ini, jadi daftarnya
        dibiarkan. Daftar kosong pada cakupan lain **mencabut**
        seluruh barisnya — pindah dari SELECTED_COMPANIES ke GLOBAL
        harus benar-benar melepas daftar lamanya, bukan
        meninggalkannya sebagai baris yatim yang akan hidup lagi kalau
        cakupannya dikembalikan.
        """
        if instance.scope != HolidayScope.SELECTED_COMPANIES:
            instance.companies.filter(is_deleted=False).update(
                is_deleted=True,
            )

            return

        if companies is None:
            return

        wanted = {company.id for company in companies}

        existing = {row.company_id: row for row in instance.companies.all()}

        for company_id, row in existing.items():
            should_be_active = company_id in wanted

            if row.is_deleted == should_be_active:
                row.is_deleted = not should_be_active
                row.save(update_fields=["is_deleted", "updated_at"])

        for company in companies:
            if company.id not in existing:
                HolidayCompany.objects.create(
                    holiday=instance,
                    company=company,
                )


class WorkCalendarSerializer(
    ScopeValidationMixin,
    OrganizationNameMixin,
    serializers.ModelSerializer,
):
    applies_to = serializers.CharField(read_only=True)

    # Tujuh kolom centang jadi satu sel: `Mon-Fri`, `Mon-Sat`,
    # `Mon,Wed,Fri`. Tujuh kolom di tabel membuat satu baris tidak
    # muat di layar, dan yang membacanya harus menggulir menyamping
    # untuk pertanyaan yang jawabannya satu kata.
    working_days = serializers.CharField(
        source="working_days_label",
        read_only=True,
    )

    class Meta:
        model = WorkCalendar
        fields = "__all__"

        read_only_fields = [
            "company_name",
            "location_name",
            "applies_to",
            "working_days",
        ]

class RosterCrewSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
    )

    location_name = serializers.CharField(
        source="location.name",
        read_only=True,
        default=None,
    )

    work_schedule_name = serializers.CharField(
        source="work_schedule.name",
        read_only=True,
    )

    cycle_pattern = serializers.SerializerMethodField()

    class Meta:
        model = RosterCrew
        fields = "__all__"

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "deleted_at",
            "deleted_by",
            "is_deleted",
            "company_name",
            "location_name",
            "work_schedule_name",
            "cycle_pattern",
        ]

    def get_cycle_pattern(self, instance) -> str:
        schedule = instance.work_schedule

        if schedule is None:
            return ""

        work = schedule.cycle_work_days
        off = schedule.cycle_off_days

        if not work or not off:
            return ""

        return f"{work} on / {off} off"
