from datetime import date

from django.core.exceptions import ValidationError
from django.db.models import Prefetch

from rest_framework.decorators import action

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.administration.models import Shift

from apps.hr.api.shift_calendar.pattern import (
    DEFAULT_ROTATION_DAYS,
    RosterShiftPatternService,
)
from apps.hr.models import (
    RotationPeriod,
    SiteRotation,
)

from .schema import (
    ROTATION_PERIOD_SCHEMA,
    SITE_ROTATION_SCHEMA,
)
from .serializers import (
    RotationPeriodSerializer,
    SiteRotationSerializer,
)
from .services import (
    RotationPeriodService,
    SiteRotationService,
)


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


class SiteRotationViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    # Penyaringan data per baris (kewenangan `RoleAssignment`). Kolom
    # organisasinya sudah tersimpan langsung di record ini; `section`
    # lewat penempatan pegawainya karena baris ini tidak menyimpannya.
    data_scope = {
        "company": "company",
        "branch": "branch",
        "location": "location",
        "division": "employee__organization__division",
        "department": "employee__organization__department",
        "section": "employee__organization__section",
        "own": "employee__user_id",
    }

    serializer_class = SiteRotationSerializer
    service_class = SiteRotationService

    framework_module = "hr/site-rotations"
    schema = SITE_ROTATION_SCHEMA

    # Default base-nya ["code", "name"], dan SiteRotation tidak punya
    # dua kolom itu — tanpa ditimpa, kotak pencarian membalas 500.
    search_fields = [
        "document_number",
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "roster_crew__code",
        "roster_crew__name",
        "location__name",
        "notes",
    ]

    filterset_fields = [
        "document_number",
        "employee",
        "company",
        "branch",
        "location",
        "roster_crew",
        "status",
        "start_date",
        "end_date",
    ]

    ordering_fields = [
        "document_number",
        "start_date",
        "end_date",
        "cycle_work_days",
        "cycle_off_days",
        "cycle_count",
        "status",
        "employee__employee_number",
        "employee__first_name",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-start_date",
        "employee__employee_number",
    ]

    def get_queryset(self):
        return (
            SiteRotation.objects
            .select_related(
                "employee",
                # Point of Hire dibaca lewat dua relasi; tanpa ini kepala
                # dokumen menambah dua query per baris daftar.
                "employee__employment",
                "employee__employment__point_of_hire",
                # Departemen/section/posisi di kepala TR; tanpa ini
                # daftar dokumen menambah tiga query per baris.
                "employee__organization",
                "employee__organization__department",
                "employee__organization__section",
                "employee__organization__position",
                "company",
                "branch",
                "location",
                "roster_crew",
            )
            .prefetch_related(
                Prefetch(
                    "periods",
                    queryset=RotationPeriod.objects.filter(
                        is_deleted=False,
                    ),
                ),
            )
            .filter(is_deleted=False)
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="generate-periods",
    )
    def generate_periods(self, request, pk=None):
        """
        Membuat ulang seluruh baris ON/OFF dokumen ini.

        Body opsional:
            {"cycle_count": 6, "force": false}

        `force` dibutuhkan kalau ada periode yang sudah disunting tangan
        atau sudah punya travel — lihat `SiteRotationService`.
        """
        rotation = self.get_object()

        user = request.user if request.user.is_authenticated else None

        # `ValidationError` dari service sengaja dibiarkan naik:
        # `meinova_exception_handler` sudah menerjemahkannya jadi 400
        # berisi error per field.
        periods = SiteRotationService.generate_periods(
            rotation=rotation,
            cycle_count=request.data.get("cycle_count"),
            force=_truthy(request.data.get("force", False)),
            user=user,
        )

        rotation.refresh_from_db()

        return success_response(
            data={
                "rotation": SiteRotationSerializer(rotation).data,
                "periods": RotationPeriodSerializer(
                    periods,
                    many=True,
                ).data,
            },
            message=f"{len(periods)} periode berhasil dibuat.",
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="extend-periods",
    )
    def extend_periods(self, request, pk=None):
        """
        Menyambung siklus baru di ujung jadwal.

        Body: `{"cycles": 3}` atau `{"until": "2027-12-31"}`

        Tidak menyentuh baris yang sudah ada — beda dengan Generate
        Periods yang membangun ulang seluruh dokumen.
        """
        rotation = self.get_object()

        until = request.data.get("until")

        if until:
            try:
                until = date.fromisoformat(str(until))
            except ValueError:
                raise ValidationError(
                    {"until": f"Tanggal tidak valid: {until!r}."},
                ) from None

        cycles = request.data.get("cycles")

        periods = SiteRotationService.extend_periods(
            rotation=rotation,
            cycles=int(cycles) if cycles else None,
            until=until or None,
            user=self._user(request),
        )

        rotation.refresh_from_db()

        return success_response(
            data={
                "rotation": SiteRotationSerializer(rotation).data,
                "periods": RotationPeriodSerializer(
                    periods,
                    many=True,
                ).data,
            },
            message=(
                f"{len(periods)} baris disambung; jadwal kini sampai "
                f"{rotation.end_date}."
            ),
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="regenerate-from",
    )
    def regenerate_from(self, request, pk=None):
        """
        Membuat ulang jadwal mulai dari satu blok, dengan pola yang
        berlaku sekarang.

        Body: `{"from_sequence": 5, "cycles": 4}`

        Baris sebelum blok itu tidak disentuh — itu sejarah yang sudah
        dijalani.
        """
        rotation = self.get_object()

        raw = request.data.get("from_sequence")

        try:
            from_sequence = int(raw)
        except (TypeError, ValueError):
            raise ValidationError(
                {
                    "from_sequence": (
                        f"from_sequence harus angka, dapat {raw!r}."
                    ),
                },
            ) from None

        cycles = request.data.get("cycles")

        periods = SiteRotationService.regenerate_from(
            rotation=rotation,
            from_sequence=from_sequence,
            cycles=int(cycles) if cycles else None,
            user=self._user(request),
        )

        rotation.refresh_from_db()

        return success_response(
            data={
                "rotation": SiteRotationSerializer(rotation).data,
                "periods": RotationPeriodSerializer(
                    periods,
                    many=True,
                ).data,
            },
            message=(
                f"{len(periods)} baris dibuat ulang dari periode "
                f"#{from_sequence}; baris sebelumnya tidak disentuh."
            ),
        )

    def _user(self, request):
        return request.user if request.user.is_authenticated else None

    @action(
        detail=True,
        methods=["post"],
        url_path="sync-shift-baseline",
    )
    def sync_shift_baseline(self, request, pk=None):
        """
        Menerbitkan ulang rencana shift dari roster + konfigurasi policy.

        Tidak menerima isian apa pun: urutan perputaran shift **milik
        Roster Policy**, bukan sesuatu yang diketik ulang tiap kali.
        Tombol ini rekonsiliasi — untuk policy yang perputarannya baru
        dikonfigurasi sesudah rosternya terbit, atau saat seseorang ingin
        memastikan rencananya memang sama dengan rosternya.

        Idempoten: dijalankan berapa kali pun hasilnya sama, dan
        penyesuaian manual tidak ikut tersapu.
        """
        rotation = self.get_object()

        result = RosterShiftPatternService.sync(
            employee=rotation.employee,
            user=self._user(request),
        )

        skipped = result.get("skipped")

        if skipped == "no_rotation":
            message = (
                "Roster Policy pegawai ini belum punya urutan perputaran "
                "shift. Isi tab Shift Rotation di layar Roster Policy, "
                "lalu jalankan lagi."
            )
        elif skipped == "no_roster":
            message = (
                "Dokumen ini belum punya blok kerja, jadi belum ada yang "
                "bisa dijadwalkan."
            )
        elif not result["created"]:
            message = (
                "Tidak ada blok kerja pada rentang jadwalnya, jadi tidak "
                "ada rencana shift yang dibuat."
            )
        else:
            message = (
                f"{result['created']} blok shift disusun dari "
                f"{result['work_blocks']} blok kerja menurut pola "
                f"{result.get('policy') or 'roster policy'}."
            )

            if result["replaced"]:
                message += (
                    f" {result['replaced']} rencana lama digantikan; "
                    "penyesuaian tidak disentuh."
                )

            message += self._rest_note(result)

        return success_response(data=result, message=message)

    @staticmethod
    def _rest_note(result) -> str:
        """
        Kalimat tambahan kalau ada hari yang **sengaja dikosongkan**.

        Hari kerja yang hilang tanpa penjelasan adalah keluhan pertama
        yang akan sampai ke HR, dan jawabannya harus ada di layar yang
        sama dengan tombolnya — bukan di dokumentasi.
        """
        rest = result.get("rest_days") or 0

        if not rest:
            return ""

        return (
            f" {rest} hari disisipkan sebagai Recovery karena jeda "
            f"pergantian shift kurang dari "
            f"{result.get('min_rest_hours')} jam; blok kerja rosternya "
            "tidak digeser."
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="apply-shift-pattern",
    )
    def apply_shift_pattern(self, request, pk=None):
        """
        Menetapkan **shift normal** untuk blok kerja dokumen ini.

        Body:
            {"shifts": [3, 5, 4], "rotation_days": 7,
             "start": "2026-09-01", "until": "2027-03-01"}

        Urutan `shifts` adalah urutan perputaran; `rotation_days`
        berapa lama satu shift dipakai sebelum berganti. Yang ditulis
        lapis **baseline** — penyesuaian yang sudah ada tetap menang
        pada rentangnya sendiri, dan tidak ada satu pun tanggal roster
        yang bergeser karenanya.

        Sengaja **bukan** `shift-periods`: yang itu menggeser tanggal.
        Dua kata "shift" yang artinya berbeda pernah ada di satu layar,
        dan itu satu-satunya alasan nama endpoint ini panjang.
        """
        rotation = self.get_object()

        shifts = self._pattern_shifts(request)

        start, until = self._pattern_range(request, rotation)

        result = RosterShiftPatternService.apply(
            employee=rotation.employee,
            shifts=shifts,
            rotation_days=self._pattern_rotation_days(request),
            start=start,
            end=until,
            user=self._user(request),
            notes=f"Pola shift roster {rotation.document_number}",
        )

        if not result["created"]:
            # Bukan error: rosternya memang tidak punya blok kerja di
            # rentang itu. Dibalas sebagai pesan supaya orangnya tahu
            # kenapa kalender tidak berubah — "berhasil" yang tidak
            # mengubah apa pun adalah kegagalan yang paling lama
            # ketahuan.
            message = (
                "Tidak ada blok kerja pada rentang tersebut, jadi tidak "
                "ada rencana shift yang dibuat. Periksa tanggalnya, "
                "atau terbitkan periode rosternya lebih dulu."
            )
        else:
            message = (
                f"{result['created']} blok shift disusun dari "
                f"{result['work_blocks']} blok kerja."
            )

            if result["replaced"]:
                message += (
                    f" {result['replaced']} rencana lama digantikan; "
                    "penyesuaian tidak disentuh."
                )

            message += self._rest_note(result)

        return success_response(data=result, message=message)

    # ------------------------------------------------------------------
    # Pembacaan body pola shift
    # ------------------------------------------------------------------

    @staticmethod
    def _pattern_shifts(request) -> list:
        raw = request.data.get("shifts") or []

        if not isinstance(raw, (list, tuple)):
            raw = [raw]

        ids = []

        for value in raw:
            try:
                ids.append(int(value))
            except (TypeError, ValueError):
                raise ValidationError(
                    {"shifts": f"Shift tidak dikenal: {value!r}."},
                ) from None

        if not ids:
            raise ValidationError({"shifts": "Pilih minimal satu shift."})

        rows = {
            shift.pk: shift
            for shift in Shift.objects.filter(
                pk__in=ids,
                is_deleted=False,
            )
        }

        missing = [value for value in ids if value not in rows]

        if missing:
            raise ValidationError(
                {"shifts": f"Shift tidak ditemukan: {missing}."},
            )

        # Urutan **kiriman**, bukan urutan query: itulah polanya.
        return [rows[value] for value in ids]

    @staticmethod
    def _pattern_rotation_days(request) -> int:
        raw = request.data.get("rotation_days")

        if raw in (None, ""):
            return DEFAULT_ROTATION_DAYS

        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ValidationError(
                {"rotation_days": f"Harus berupa angka, dapat {raw!r}."},
            ) from None

    @staticmethod
    def _pattern_range(request, rotation) -> tuple[date, date]:
        def parse(name, fallback):
            raw = request.data.get(name)

            if raw in (None, ""):
                return fallback

            try:
                return date.fromisoformat(str(raw))
            except ValueError:
                raise ValidationError(
                    {name: f"Tanggal tidak valid: {raw!r}."},
                ) from None

        # Bawaannya seluruh rentang dokumen, bukan "mulai hari ini":
        # yang paling sering dilakukan adalah menyusun rencana untuk
        # roster yang baru terbit, dan rosternya lazim mulai bulan
        # depan. Rentang yang diam-diam memotong depannya membuat
        # tanggal awal blok kerja pertama tidak punya shift.
        #
        # Kalau kepala dokumen tidak membawa tanggalnya, yang dipakai
        # **blok kerjanya sendiri** — dokumen jalur lama cuma menyimpan
        # tanggal mulai, dan rentang yang jatuh ke sehari menerbitkan
        # rencana satu hari: berhasil, kosong, dan tidak terbaca sebagai
        # kegagalan oleh siapa pun.
        first, last = RosterShiftPatternService.schedule_bounds(
            rotation.employee,
        )

        start = parse(
            "start",
            rotation.start_date or rotation.cycle_start or first,
        )

        end = parse(
            "until",
            rotation.horizon_end or rotation.end_date or last or start,
        )

        if start is None or end is None:
            raise ValidationError(
                {
                    "start": (
                        "Dokumen ini belum punya tanggal jadwal; isi "
                        "rentangnya sendiri."
                    ),
                },
            )

        return start, end

    @action(
        detail=True,
        methods=["post"],
        url_path="shift-periods",
    )
    def shift_periods(self, request, pk=None):
        """
        Menggeser satu periode beserta sisa jadwalnya.

        Body:
            {"from_sequence": 3, "days": -2}

        `days` positif memundurkan, negatif memajukan. Travel dan
        tanggal akomodasi ikut bergeser — lihat
        `SiteRotationService.shift_from`.
        """
        rotation = self.get_object()

        user = request.user if request.user.is_authenticated else None

        payload = {}

        for name in ("from_sequence", "days"):
            raw = request.data.get(name)

            try:
                payload[name] = int(raw)
            except (TypeError, ValueError):
                # Dibalas sebagai error per field, bukan 500: keduanya
                # diketik orang, dan salah ketik harus sampai ke form
                # sebagai pesan yang bisa dibaca.
                raise ValidationError(
                    {name: f"{name} harus berupa angka, dapat {raw!r}."},
                ) from None

        periods = SiteRotationService.shift_from(
            rotation=rotation,
            user=user,
            **payload,
        )

        rotation.refresh_from_db()

        direction = (
            "dimundurkan"
            if payload["days"] > 0
            else "dimajukan"
        )

        return success_response(
            data={
                "rotation": SiteRotationSerializer(rotation).data,
                "periods": RotationPeriodSerializer(
                    periods,
                    many=True,
                ).data,
            },
            message=(
                f"{len(periods)} periode {direction} "
                f"{abs(payload['days'])} hari."
            ),
        )


class RotationPeriodViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = RotationPeriodSerializer
    service_class = RotationPeriodService

    framework_module = "hr/rotation-periods"
    schema = ROTATION_PERIOD_SCHEMA

    search_fields = [
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "notes",
    ]

    filterset_fields = [
        "rotation",
        "employee",
        "period_type",
        "purpose",
        "status",
        "is_manual_override",
        "start_date",
        "end_date",
    ]

    ordering_fields = [
        "sequence",
        "start_date",
        "end_date",
        "total_days",
        "period_type",
        "status",
        "employee__employee_number",
        "created_at",
        "updated_at",
    ]

    # Kronologis dulu — baris sisipan mendapat nomor urut terakhir yang
    # bebas, jadi mengurutkannya dari nomor akan melemparnya ke dasar
    # tabel, jauh dari blok yang dipecahnya.
    ordering = [
        "rotation",
        "start_date",
        "sequence",
    ]

    def get_queryset(self):
        return (
            RotationPeriod.objects
            .select_related(
                "rotation",
                "employee",
                "purpose",
                "employee_leave",
            )
            .filter(is_deleted=False)
        )
