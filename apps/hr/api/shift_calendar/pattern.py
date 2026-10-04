"""
Rencana shift normal yang lahir **dari roster**, bukan dari layar kedua.

Kenapa berkas ini ada
---------------------
Roster menjawab kapan seseorang bekerja; `EmployeeShiftAssignment`
menjawab shift apa. Keduanya memang tabel terpisah — lihat
`apps/hr/models/shift_assignment.py` — tapi sebelum ini tidak ada satu
pun jalur yang menghubungkan mereka. Akibatnya pengguna HR menyusun
roster sekali di dokumen Roster Schedule, lalu **menyusunnya lagi**
sebagai baris penugasan shift satu per satu, sambil memilih sendiri
lapis "Roster Baseline" — sebuah istilah yang seharusnya tidak pernah
sampai ke layar.

Yang dikerjakan berkas ini cuma satu: membaca blok kerja yang sudah ada
lalu menempelkan pola shift ke atasnya sebagai lapis `BASELINE`. Ia
tidak menerbitkan roster, tidak menggeser tanggal, dan tidak pernah
memutuskan seseorang bekerja atau tidak — `RotationPeriod` tetap
satu-satunya yang menjawab itu.

Tiga aturan bentuknya
---------------------
**Polanya dijangkarkan ke awal blok kerja**, bukan ke tanggal perintah
dijalankan. Karena itu menerapkan pola dari tengah blok menghasilkan
shift yang sama dengan menerapkannya dari awal blok — kalau tidak,
"minggu keberapa saya sekarang" berubah tiap kali seseorang menekan
tombolnya.

**Adjustment tidak pernah disentuh.** Yang dibersihkan sebelum menulis
hanya lapis `BASELINE`; penyesuaian supervisor yang sudah disetujui
tetap menang atas rencana baru pada rentangnya sendiri. Menghapus
keduanya akan membuat "perbarui rencana shift" diam-diam membatalkan
keputusan orang lain.

**Baris baseline lama yang cuma tersentuh sebagian dipotong, bukan
dibuang.** Rencana Juli yang ujungnya masuk ke rentang baru tetap
berlaku untuk hari-hari Juli-nya. Membuang seluruh barisnya membuat
tanggal di luar rentang kehilangan jadwal tanpa ada yang memintanya.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import models, transaction

from apps.hr.api.attendance.schedule import shift_span
from apps.hr.models import (
    EmployeeShiftAssignment,
    RosterSegmentType,
    RotationPeriod,
    RotationPeriodStatus,
    ShiftAssignmentKind,
    ShiftAssignmentLayer,
)


# Bawaan mingguan: itu yang dijalani crew tambang, dan yang dipakai
# seluruh data peragaan. Tetap sebuah **bawaan**, bukan aturan — site
# yang berputar tiap 10 hari cukup mengganti angkanya di dialog.
DEFAULT_ROTATION_DAYS = 7

# Pagar, bukan kebijakan. Yang dijaga: satu salah ketik tidak boleh
# menerbitkan ribuan baris untuk tanggal yang tidak dilihat siapa pun.
MAX_ROTATION_DAYS = 180
MAX_PLAN_DAYS = 732
MAX_PATTERN_SHIFTS = 12


def _one_day() -> timedelta:
    return timedelta(days=1)


class RosterShiftPatternService:
    """Menerjemahkan blok kerja roster jadi rencana shift `BASELINE`."""

    # ------------------------------------------------------------------
    # Baca roster
    # ------------------------------------------------------------------

    @staticmethod
    def work_segments(employee, start: date, end: date) -> list:
        """
        Blok kerja aktif yang menyentuh rentang, urut tanggal.

        Sengaja memakai `version_to__isnull=True`: versi lama sebuah
        rencana adalah sejarah, dan menempelkan shift ke sejarah berarti
        menerbitkan rencana untuk tanggal yang sudah diganti.
        """
        return list(
            RotationPeriod.objects
            .filter(
                employee=employee,
                is_deleted=False,
                version_to__isnull=True,
                segment_type=RosterSegmentType.WORK,
                start_date__lte=end,
                end_date__gte=start,
            )
            .exclude(status=RotationPeriodStatus.CANCELLED)
            .order_by("start_date")
        )

    @staticmethod
    def schedule_bounds(employee) -> tuple[date | None, date | None]:
        """
        Tanggal pertama dan terakhir blok kerja pegawai — `(None, None)`
        kalau rosternya memang belum punya periode.

        Dipakai sebagai rentang bawaan tombol Set Shift Pattern. Kepala
        dokumen roster tidak selalu membawa `horizon_end`: dokumen yang
        dibuat lewat jalur lama hanya menyimpan tanggal mulai, dan
        rentang yang jatuh ke "sehari" menghasilkan rencana shift satu
        hari — berhasil, kosong, dan tidak terbaca sebagai kegagalan.
        """
        bounds = (
            RotationPeriod.objects
            .filter(
                employee=employee,
                is_deleted=False,
                version_to__isnull=True,
                segment_type=RosterSegmentType.WORK,
            )
            .exclude(status=RotationPeriodStatus.CANCELLED)
            .aggregate(
                first=models.Min("start_date"),
                last=models.Max("end_date"),
            )
        )

        return bounds["first"], bounds["last"]

    # ------------------------------------------------------------------
    # Rumus pola
    # ------------------------------------------------------------------

    @staticmethod
    def steps_from(shifts, rotation_days: int = DEFAULT_ROTATION_DAYS):
        """`[(shift, hari)]` dari pola yang panjang langkahnya seragam."""
        return [(shift, rotation_days) for shift in shifts]

    @staticmethod
    def _step_at(steps, offset: int) -> tuple:
        """
        `(shift, mulai_langkah, akhir_langkah)` untuk hari ke-`offset`
        sejak awal blok kerja — **tanpa** memperhitungkan hari pemulihan.

        Panjang langkah boleh berbeda-beda — "dua minggu malam lalu satu
        minggu pagi" adalah pola yang nyata, dan memaksakan satu angka
        untuk semua langkah membuatnya harus ditulis sebagai tiga baris
        yang isinya sama.

        Dipertahankan sebagai rumus murni untuk pemanggil yang ingin
        menjawab "langkah keberapa hari ini" tanpa menyusun rencana.
        `build_plan()` **tidak** lagi memakainya: begitu hari pemulihan
        bisa disisipkan, hari ke-N tidak lagi bisa dijawab satu modulo.
        """
        cycle = sum(days for _, days in steps)

        position = offset % cycle
        anchor = offset - position

        for shift, days in steps:
            if position < days:
                return shift, anchor, anchor + days - 1

            position -= days
            anchor += days

        # Tidak terjangkau selama `cycle` benar; dikembalikan langkah
        # terakhir supaya kesalahan aritmetika tidak jadi `None` yang
        # meledak jauh dari sebabnya.
        shift, days = steps[-1]

        return shift, anchor - days, anchor - 1

    # ------------------------------------------------------------------
    # Jeda antar shift
    # ------------------------------------------------------------------

    @staticmethod
    def shift_window(day: date, shift) -> tuple[datetime, datetime]:
        """
        `(mulai, selesai)` sebuah shift pada satu tanggal, sebagai
        datetime naif.

        Aturan lewat-tengah-malamnya **dipinjam**, bukan ditulis ulang:
        `shift_span()` milik `apps.hr.api.attendance.schedule` adalah
        fungsi yang sama yang dipakai kalender dan importer. Kalau
        penyusun rencana memakai rumusnya sendiri, "jam berapa shift
        malam selesai" punya dua jawaban — dan yang satu akan menyimpang
        diam-diam.
        """
        return shift_span(
            day,
            shift.start_time,
            shift.end_time,
            bool(shift.crosses_midnight),
        )

    @classmethod
    def rest_hours_between(
        cls,
        *,
        previous_end: datetime,
        day: date,
        shift,
    ) -> float:
        """
        Berapa jam istirahat yang benar-benar tersisa sebelum `shift`
        mulai pada `day`.

        Dihitung dari **datetime**, bukan dari selisih tanggal. Itu yang
        membuat aturannya bisa dipakai site mana pun: Night 19:00–07:00
        yang disusul Day 07:00 keesokan harinya berjarak satu hari di
        kalender dan **nol jam** dalam kenyataan, dan yang kedua itulah
        yang menentukan orangnya sempat tidur atau tidak.
        """
        begin, _ = cls.shift_window(day, shift)

        return (begin - previous_end).total_seconds() / 3600

    # ------------------------------------------------------------------
    # Rencana
    # ------------------------------------------------------------------

    @staticmethod
    def _same_shift(left, right) -> bool:
        if left is None or right is None:
            return left is None and right is None

        return left.pk == right.pk

    @classmethod
    def _emit(cls, plan: list, shift, day: date) -> None:
        """
        Menempelkan satu hari ke rencana, menyatu dengan hari sebelumnya
        kalau isinya sama.

        Potongan berurutan dengan shift yang sama disatukan. Pola satu
        shift seharusnya menghasilkan **satu** baris per blok, bukan
        satu baris per minggu yang isinya sama — daftar penugasan yang
        panjangnya tidak masuk akal membuat orang mengira sistemnya
        menulis sampah. Berlaku sama untuk hari pemulihan berturut-turut.
        """
        if (
            plan
            and cls._same_shift(plan[-1][0], shift)
            and plan[-1][2] + _one_day() == day
        ):
            plan[-1] = (shift, plan[-1][1], day)
        else:
            plan.append((shift, day, day))

    @classmethod
    def build_plan(
        cls,
        *,
        segments,
        shifts=None,
        rotation_days: int = DEFAULT_ROTATION_DAYS,
        steps=None,
        start: date | None = None,
        end: date | None = None,
        min_rest_hours: int = 0,
    ) -> list[tuple]:
        """
        `[(shift, mulai, selesai), …]` — tanpa satu query pun.

        Itu yang membuat rumusnya bisa diuji tanpa menyiapkan tenant,
        dan dipakai jalur yang sama oleh seed, tombol pola manual, dan
        sinkronisasi otomatis dari konfigurasi policy.

        Dua bentuk masukan, dan yang kedua yang umum: `shifts` +
        `rotation_days` (semua langkah sepanjang itu) atau `steps` berisi
        `(shift, hari)` per langkah.

        **`shift` boleh `None`** — itu hari pemulihan, dan ia hanya
        muncul kalau `min_rest_hours` lebih dari nol.

        Jeda minimum antar shift
        ------------------------
        Diperiksa **hanya saat shift benar-benar berganti**. Hari kedua
        sebuah blok malam berjarak 12 jam dari hari pertamanya, dan itu
        jeda harian biasa — memberlakukan aturan pergantian di sana akan
        menyisipkan hari pemulihan di antara setiap dua malam berturutan.

        Kalau jedanya kurang, satu hari pemulihan disisipkan lalu
        jedanya **diukur ulang** — bukan dihitung "sekian hari" sekali
        jalan. Itu yang membuat aturannya benar untuk pergantian mana
        pun: Night 19:00–07:00 → Day 07:00 butuh satu hari untuk
        mencapai 24 jam, sedangkan Night → Afternoon 15:00 sudah cukup
        dengan delapan jam pertamanya.

        Perhitungannya berjalan dari **awal blok kerja** dan menyeberang
        batas blok: shift terakhir yang benar-benar terbit tetap diingat
        walau blok berikutnya memulai perputarannya dari langkah
        pertama. Blok yang dipisahkan field break otomatis lolos —
        jedanya memang ratusan jam — dan yang bersambungan langsung
        tidak, dan keduanya keluar dari aritmetika yang sama.
        """
        if steps is None:
            steps = cls.steps_from(shifts or [], rotation_days)

        if not steps:
            return []

        plan: list[tuple] = []

        # Shift terakhir yang benar-benar terbit, dan jam selesainya.
        # Disimpan di luar loop segmen dengan sengaja — batas antar blok
        # kerja adalah pergantian shift juga, dan yang membedakannya dari
        # pergantian di dalam blok cuma panjang jedanya.
        last_shift = None
        last_end = None

        for segment in segments:
            block_start = segment.start_date

            stop = segment.end_date

            if end is not None and end < stop:
                stop = end

            # Indeks langkah dihitung dari **awal blok**, dan simulasinya
            # pun berangkat dari sana walau yang diminta cuma ekornya:
            # menerapkan pola mulai pertengahan blok harus mendarat di
            # shift yang sama dengan menerapkannya dari awal. Sejak hari
            # pemulihan bisa disisipkan, itu tidak lagi bisa dijawab satu
            # modulo — yang bisa menjawabnya cuma menjalani harinya.
            step_index = 0
            used = 0

            day = block_start

            while day <= stop:
                shift, step_days = steps[step_index]

                if (
                    min_rest_hours > 0
                    and last_shift is not None
                    and not cls._same_shift(last_shift, shift)
                ):
                    while day <= stop and cls.rest_hours_between(
                        previous_end=last_end,
                        day=day,
                        shift=shift,
                    ) < min_rest_hours:
                        if start is None or day >= start:
                            cls._emit(plan, None, day)

                        day += _one_day()

                    if day > stop:
                        break

                if start is None or day >= start:
                    cls._emit(plan, shift, day)

                # Jam selesainya cuma dihitung kalau memang ada yang
                # mau membandingkannya. Aturan yang mati harus berarti
                # jalurnya **tidak dilewati sama sekali** — bukan
                # dilewati lalu hasilnya dibuang: policy yang belum
                # mengisi angkanya adalah keadaan bawaan setiap tenant,
                # dan jalur bawaan tidak boleh ikut menanggung biaya
                # maupun risiko aturan yang belum dipakai siapa pun.
                last_shift = shift

                if min_rest_hours > 0:
                    _, last_end = cls.shift_window(day, shift)

                day += _one_day()
                used += 1

                if used >= step_days:
                    step_index = (step_index + 1) % len(steps)
                    used = 0

        return plan

    # ------------------------------------------------------------------
    # Tulis
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def apply(
        cls,
        *,
        employee,
        shifts=None,
        rotation_days: int = DEFAULT_ROTATION_DAYS,
        steps=None,
        start: date,
        end: date,
        clear_start: date | None = None,
        clear_end: date | None = None,
        min_rest_hours: int | None = None,
        user=None,
        notes: str = "",
    ) -> dict:
        if steps is None:
            steps = cls.steps_from(shifts or [], rotation_days)

        # Dibaca dari policy pegawainya kalau pemanggil tidak
        # menyebutnya. Itu yang membuat tombol **Set Shift Pattern
        # (Manual)** ikut menghormati aturan jeda tanpa satu kolom
        # tambahan pun di dialognya: aturannya milik site, bukan milik
        # pola yang kebetulan sedang diketik seseorang.
        if min_rest_hours is None:
            min_rest_hours = cls.min_rest_hours_for(employee)

        cls._validate(steps=steps, start=start, end=end)

        segments = cls.work_segments(employee, start, end)

        plan = cls.build_plan(
            segments=segments,
            steps=steps,
            start=start,
            end=end,
            min_rest_hours=min_rest_hours,
        )

        # Jendela pembersihan boleh lebih lebar dari jendela rencana.
        # Itu yang membuat rekonsiliasi benar-benar bekerja: blok kerja
        # yang digeser maju meninggalkan baris rencana di tanggal yang
        # sudah bukan hari kerja, dan baris itu tidak akan pernah
        # tersentuh kalau yang dibersihkan cuma rentang barunya.
        cleared = cls.clear_baseline(
            employee=employee,
            start=clear_start or start,
            end=clear_end or end,
            user=user,
        )

        # Diimpor di sini, bukan di kepala berkas: `services` mengimpor
        # resolver yang mengimpor model, dan kedua arah impor di kepala
        # berkas membuat lingkaran yang baru meledak saat app dimuat.
        from apps.hr.api.shift_calendar.services import (
            EmployeeShiftAssignmentService,
        )

        blocks = []

        rest_days = 0

        for shift, block_start, block_end in plan:
            is_rest = shift is None

            days = (block_end - block_start).days + 1

            EmployeeShiftAssignmentService.create(
                data={
                    "employee": employee,
                    "shift": shift,
                    "kind": (
                        ShiftAssignmentKind.REST
                        if is_rest
                        else ShiftAssignmentKind.WORK
                    ),
                    "layer": ShiftAssignmentLayer.BASELINE,
                    "start_date": block_start,
                    "end_date": block_end,
                    "notes": notes,
                },
                user=user,
            )

            if is_rest:
                rest_days += days

            blocks.append(
                {
                    "shift_id": None if is_rest else shift.pk,
                    "shift_code": "" if is_rest else shift.code,
                    "shift_name": "" if is_rest else shift.name,
                    # Dikirim eksplisit, bukan disimpulkan dari
                    # `shift_code` yang kosong: layar dan seed sama-sama
                    # membacanya, dan "kosong berarti pemulihan" adalah
                    # aturan tak tertulis yang akan salah dibaca pertama
                    # kali ada blok yang shift-nya memang belum lengkap.
                    "kind": (
                        ShiftAssignmentKind.REST
                        if is_rest
                        else ShiftAssignmentKind.WORK
                    ),
                    "start_date": block_start,
                    "end_date": block_end,
                    "days": days,
                },
            )

        return {
            "employee_id": employee.pk,
            "start": start,
            "end": end,
            "rotation_days": (
                steps[0][1] if len(set(d for _, d in steps)) == 1 else None
            ),
            "work_blocks": len(segments),
            "created": len(blocks),
            "replaced": cleared,
            "min_rest_hours": min_rest_hours,
            "rest_days": rest_days,
            "blocks": blocks,
        }

    # ------------------------------------------------------------------
    # Membersihkan rencana lama
    # ------------------------------------------------------------------

    @classmethod
    def clear_baseline(
        cls,
        *,
        employee,
        start: date,
        end: date,
        user=None,
    ) -> int:
        """
        Mengosongkan lapis `BASELINE` pada rentang — dan hanya di sana.

        Mengembalikan jumlah baris yang tersentuh. Baris yang menjulur
        keluar rentang dipotong; yang menaungi seluruh rentang dipotong
        di depan lalu ekornya diterbitkan ulang sebagai baris tersendiri.
        """
        from apps.hr.api.shift_calendar.services import (
            EmployeeShiftAssignmentService,
        )

        rows = list(
            EmployeeShiftAssignment.objects
            .filter(
                employee=employee,
                is_deleted=False,
                layer=ShiftAssignmentLayer.BASELINE,
                start_date__lte=end,
                end_date__gte=start,
            )
            .select_related("shift")
            .order_by("start_date"),
        )

        touched = 0

        for row in rows:
            leading = row.start_date < start
            trailing = row.end_date > end

            tail = (
                (end + _one_day(), row.end_date)
                if trailing and leading
                else None
            )

            if leading:
                EmployeeShiftAssignmentService.update(
                    instance=row,
                    data={"end_date": start - _one_day()},
                    user=user,
                )
            elif trailing:
                EmployeeShiftAssignmentService.update(
                    instance=row,
                    data={"start_date": end + _one_day()},
                    user=user,
                )
            else:
                EmployeeShiftAssignmentService.delete(
                    instance=row,
                    user=user,
                )

            if tail is not None:
                # Ditulis **sesudah** barisnya dipotong: sebelum itu
                # rentangnya masih tumpang tindih dengan induknya, dan
                # `clean()` menolaknya — dengan benar.
                EmployeeShiftAssignmentService.create(
                    data={
                        "employee": employee,
                        "shift": row.shift,
                        # Ekornya adalah **baris yang sama**, cuma
                        # tanggalnya lebih pendek. Hari pemulihan yang
                        # terbit ulang sebagai baris kerja tanpa shift
                        # akan ditolak `clean()`, dan yang terbit sebagai
                        # baris kerja dengan shift justru lolos diam-diam
                        # lalu menagih presensi di hari istirahat.
                        "kind": row.kind,
                        "layer": ShiftAssignmentLayer.BASELINE,
                        "start_date": tail[0],
                        "end_date": tail[1],
                        "notes": row.notes,
                    },
                    user=user,
                )

            touched += 1

        return touched

    # ------------------------------------------------------------------
    # Jalur otomatis: konfigurasi policy → baseline
    # ------------------------------------------------------------------

    @staticmethod
    def rotation_steps(policy) -> list[tuple]:
        """
        `[(shift, hari)]` dari `RosterShiftRotation` milik sebuah policy.

        Kosong = policy itu memang belum dikonfigurasi perputarannya, dan
        itu **bukan** kesalahan: banyak site cuma punya satu shift dan
        memakai shift permanen pegawainya. Pemanggil yang memutuskan apa
        artinya — yang jelas bukan menebak sebuah shift.
        """
        if policy is None:
            return []

        return [
            (row.shift, row.block_days or DEFAULT_ROTATION_DAYS)
            for row in (
                policy.shift_rotations
                .filter(is_deleted=False, is_active=True)
                .select_related("shift")
                .order_by("sequence")
            )
            if row.shift_id
        ]

    @staticmethod
    def baseline_bounds(employee) -> tuple[date | None, date | None]:
        """Tanggal terawal dan terakhir lapis `BASELINE` yang masih hidup."""
        bounds = (
            EmployeeShiftAssignment.objects
            .filter(
                employee=employee,
                is_deleted=False,
                layer=ShiftAssignmentLayer.BASELINE,
            )
            .aggregate(
                first=models.Min("start_date"),
                last=models.Max("end_date"),
            )
        )

        return bounds["first"], bounds["last"]

    @classmethod
    def policy_for(cls, employee):
        """
        Policy yang menentukan perputaran shift pegawai ini.

        Dibaca dari penempatannya, sumber yang **sama** dengan yang
        dipakai `RosterPolicyResolver` untuk hari perjalanan dan rasio
        kredit. Menambah jalur resolusi kedua di sini berarti dua jawaban
        untuk "policy siapa yang berlaku", dan yang kedua akan menyimpang
        diam-diam.
        """
        employment = getattr(employee, "employment", None)

        return getattr(employment, "roster_policy", None)

    @classmethod
    def min_rest_hours_for(cls, employee) -> int:
        """
        Jeda istirahat minimum yang berlaku untuk pegawai ini, dalam jam.

        Nol untuk pegawai tanpa policy — dan itu **bukan** kelalaian:
        pegawai yang tidak dicakup aturan roster mana pun tidak boleh
        kehilangan hari kerja karena angka bawaan yang tidak pernah
        diputuskan siapa pun.
        """
        policy = cls.policy_for(employee)

        return int(getattr(policy, "min_rest_hours", 0) or 0)

    @classmethod
    @transaction.atomic
    def sync(
        cls,
        *,
        employee,
        start: date | None = None,
        end: date | None = None,
        user=None,
        notes: str = "",
    ) -> dict:
        """
        Menerbitkan ulang rencana shift `BASELINE` dari roster + policy.

        **Idempoten**: hasilnya ditentukan sepenuhnya oleh blok kerja
        yang berlaku sekarang dan konfigurasi perputaran policy-nya, jadi
        menjalankannya dua kali menghasilkan baris yang sama persis.
        Itu pula yang membuatnya aman dipanggil setiap kali roster
        berubah — rekonsiliasi, bukan penambahan.

        **Penyesuaian tidak pernah disentuh.** Yang ditulis ulang hanya
        lapis `BASELINE`; `OVERRIDE` tetap menang pada rentangnya sendiri
        walau rosternya digeser.

        Mengembalikan rekap, termasuk `reason` kalau tidak ada yang bisa
        dikerjakan — "berhasil" yang tidak mengubah apa pun adalah
        kegagalan yang paling lama ketahuan.
        """
        policy = cls.policy_for(employee)

        steps = cls.rotation_steps(policy)

        if not steps:
            return {
                "employee_id": employee.pk,
                "created": 0,
                "replaced": 0,
                "work_blocks": 0,
                "blocks": [],
                "min_rest_hours": cls.min_rest_hours_for(employee),
                "rest_days": 0,
                "skipped": "no_rotation",
                "policy": getattr(policy, "name", "") or "",
            }

        first, last = cls.schedule_bounds(employee)

        start = start or first
        end = end or last

        if start is None or end is None:
            # Rosternya habis — dihapus, di-reset, atau seluruh
            # periodenya dibatalkan. Rencana `BASELINE` yang pernah
            # diterbitkannya **ikut dibersihkan**, bukan ditinggalkan:
            # `EmployeeShiftAssignment` tidak punya FK ke roster sama
            # sekali, jadi tanpa baris ini Shift Calendar tetap
            # menampilkan shift di tanggal yang rosternya sudah tidak
            # ada — dan itu jenis kesalahan yang paling lama tidak
            # ketahuan, karena layarnya terlihat terisi.
            #
            # `OVERRIDE` tidak disentuh, sama seperti jalur normal:
            # penyesuaian adalah keputusan orang, bukan turunan roster.
            owned_start, owned_end = cls.baseline_bounds(employee)

            cleared = 0

            if owned_start is not None and owned_end is not None:
                cleared = cls.clear_baseline(
                    employee=employee,
                    start=owned_start,
                    end=owned_end,
                    user=user,
                )

            return {
                "employee_id": employee.pk,
                "created": 0,
                "replaced": cleared,
                "cleared": cleared,
                "work_blocks": 0,
                "blocks": [],
                "min_rest_hours": cls.min_rest_hours_for(employee),
                "rest_days": 0,
                "skipped": "no_roster",
                "policy": getattr(policy, "name", "") or "",
            }

        # Rencana sepanjang horizon roster bisa melewati pagar
        # `MAX_PLAN_DAYS`. Dipotong, bukan ditolak: yang diminta
        # pemanggil "samakan dengan roster", dan menolak seluruhnya
        # karena rosternya panjang berarti tidak ada jadwal sama sekali.
        span = (end - start).days + 1

        if span > MAX_PLAN_DAYS:
            end = start + timedelta(days=MAX_PLAN_DAYS - 1)

        # Sinkronisasi memiliki **seluruh** lapis baseline pegawai ini:
        # yang dibersihkan bukan cuma rentang jadwal barunya, tapi juga
        # rentang yang pernah ditulisnya. Tanpa itu, roster yang digeser
        # meninggalkan rencana lama di tanggal yang sudah bukan hari
        # kerja — tidak terlihat di kalender (hari bukan kerja memang
        # tidak dibaca), tapi tetap terbaca sebagai jadwal di layar
        # Records dan di ekspor.
        owned_start, owned_end = cls.baseline_bounds(employee)

        result = cls.apply(
            employee=employee,
            steps=steps,
            start=start,
            end=end,
            clear_start=min(start, owned_start or start),
            clear_end=max(end, owned_end or end),
            user=user,
            notes=notes or "Baseline shift dari roster policy",
        )

        result["skipped"] = ""
        result["policy"] = getattr(policy, "name", "") or ""

        return result

    # ------------------------------------------------------------------
    # Penjagaan
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(*, steps, start: date, end: date):
        errors = {}

        if not steps:
            errors["shifts"] = "Pilih minimal satu shift."
        elif len(steps) > MAX_PATTERN_SHIFTS:
            errors["shifts"] = (
                f"Maksimal {MAX_PATTERN_SHIFTS} shift dalam satu pola; "
                f"dipilih {len(steps)}."
            )

        for _, days in steps:
            if days < 1:
                errors["rotation_days"] = "Minimal 1 hari."
                break

            if days > MAX_ROTATION_DAYS:
                errors["rotation_days"] = (
                    f"Maksimal {MAX_ROTATION_DAYS} hari."
                )
                break

        if end < start:
            errors["until"] = "Tanggal akhir tidak boleh sebelum mulai."
        elif (end - start).days + 1 > MAX_PLAN_DAYS:
            errors["until"] = (
                f"Rentang maksimal {MAX_PLAN_DAYS} hari; diminta "
                f"{(end - start).days + 1}."
            )

        if errors:
            raise ValidationError(errors)
