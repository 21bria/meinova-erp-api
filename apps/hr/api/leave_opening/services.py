"""
Menerjemahkan dokumen saldo awal jadi angka di kartu cuti.

Arahnya satu: dokumen → kartu. `LeaveBalance.opening_balance`
**dijumlah ulang** dari baris `LeaveOpeningBalance` yang aktif, persis
seperti `used` yang dijumlah ulang dari catatan cuti. Penjumlahan ulang
tidak bisa hanyut; menambah/mengurangi inkremental bisa, dan selisihnya
baru ketahuan berbulan-bulan kemudian saat ada yang mencocokkan angka.

Yang tidak disentuh sama sekali: `entitlement`, `carried_over`,
`adjustment`, dan `used`. Keempatnya punya pemiliknya masing-masing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.services.master import BaseMasterService
from apps.hr.api.leave.entitlement import LeavePolicyResolver, add_months
from apps.hr.models import (
    LeaveBalance,
    LeaveOpeningBalance,
    LeaveOpeningStatus,
)


class LeaveOpeningBalanceService(BaseMasterService):
    model = LeaveOpeningBalance

    # ------------------------------------------------------------------
    # Nilai turunan
    # ------------------------------------------------------------------

    @classmethod
    def apply_opening_date(cls, data: dict[str, Any]) -> dict[str, Any]:
        """
        Tanggal berlaku, diambil dari go-live perusahaan pegawainya.

        Ini yang membuat langkah pertama punya buah: tanggal itu sudah
        ditetapkan sekali, dan mengetiknya ulang di tiap baris cuma
        menambah kesempatan salah ketik — satu baris yang meleset ke
        tahun lain akan mendarat di kartu saldo tahun yang salah, dan
        yang membacanya cuma melihat saldo pegawai itu nol.

        Yang diketik orang selalu menang: perusahaan yang menyerahkan
        datanya bertahap memang punya baris bertanggal lain.
        """
        if data.get("opening_date"):
            return data

        employee = data.get("employee")

        if employee is None:
            return data

        from apps.hr.api.leave.go_live import LeaveGoLiveResolver

        go_live = LeaveGoLiveResolver.for_employee(employee)

        if go_live is None or go_live.go_live_date is None:
            raise ValidationError(
                {
                    "opening_date": (
                        "Tanggal berlaku kosong dan perusahaan pegawai "
                        "ini belum punya tanggal go-live cuti. Isi "
                        "Leave Go-Live dulu, atau tulis tanggalnya di "
                        "sini."
                    ),
                },
            )

        data["opening_date"] = go_live.go_live_date

        return data

    @classmethod
    def apply_year(cls, data: dict[str, Any]) -> dict[str, Any]:
        """
        Tahun kartu tujuan, diturunkan dari tanggal berlaku.

        Boleh diisi eksplisit — tenant yang policy-nya berbasis tanggal
        masuk kadang perlu menaruh saldo go-live di kartu tahun
        berikutnya. Yang tidak boleh cuma mengosongkannya.
        """
        if data.get("year"):
            return data

        opening_date = data.get("opening_date")

        if isinstance(opening_date, date):
            data["year"] = opening_date.year

        return data

    @classmethod
    def apply_expiry(cls, data: dict[str, Any]) -> dict[str, Any]:
        """
        Tanggal hangus, dihitung **sekali** dari policy lalu dibekukan.

        Anchor-nya `opening_date`, bukan 1 Januari seperti sisa bawaan
        tahun lalu. Alasannya beda titik lahir: sisa bawaan lahir saat
        tahun berganti, saldo awal lahir saat ERP mulai dipakai. Kalau
        anchor-nya ikut 1 Januari, tenant yang go-live bulan Agustus
        dengan masa berlaku 6 bulan mendapat tanggal hangus yang
        **sudah lewat** pada hari pertama sistemnya dipakai.

        Nilai yang sudah diisi orang selalu menang: masa berlaku hasil
        kesepakatan dengan klien tidak selalu sama dengan yang tertulis
        di policy.
        """
        if data.get("expires_at"):
            return data

        employee = data.get("employee")
        leave_type = data.get("leave_type")
        opening_date = data.get("opening_date")

        if not (employee and leave_type and isinstance(opening_date, date)):
            return data

        policy = LeavePolicyResolver.resolve(
            employee=employee,
            leave_type=leave_type,
        )

        if policy is None or not policy.allow_carry_over:
            return data

        months = policy.carry_over_expiry_months

        if not months:
            return data

        data["expires_at"] = add_months(opening_date, int(months))

        return data

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.assert_uses_balance(data)

        data = cls.apply_opening_date(data)
        data = cls.apply_year(data)
        data = cls.apply_expiry(data)

        return data

    @classmethod
    def assert_uses_balance(
        cls,
        data: dict[str, Any],
        *,
        instance=None,
    ) -> None:
        """
        Saldo awal hanya untuk jenis cuti yang memang bersaldo.

        Cuti menikah dan melahirkan tidak punya kartu untuk diisi:
        `LeaveBalanceGenerator` tidak menerbitkannya, dan
        `sync_balance` tidak akan menemukan baris tujuan. Tanpa
        penolakan di sini dokumennya tetap tersimpan dan tetap bisa
        di-post — lalu angkanya tidak pernah muncul di mana pun, dan
        yang mengimpornya menyimpulkan filenya yang salah.

        Jenis cuti yang **belum punya policy sama sekali** sengaja
        tetap diterima: itu keadaan yang sah selama masternya belum
        diisi, dan menolaknya akan menghentikan migrasi tenant yang
        justru sedang menyiapkan datanya.
        """
        def resolved(name):
            if name in data:
                return data[name]

            return getattr(instance, name, None)

        employee = resolved("employee")
        leave_type = resolved("leave_type")

        if employee is None or leave_type is None:
            return

        policy = LeavePolicyResolver.resolve(
            employee=employee,
            leave_type=leave_type,
        )

        if policy is None or policy.uses_balance:
            return

        raise ValidationError(
            {
                "leave_type": (
                    f"{leave_type.name} bukan cuti bersaldo menurut "
                    f"{policy.code}, jadi tidak punya kartu saldo "
                    f"untuk diisi. Saldo awal hanya untuk jenis cuti "
                    f"yang Uses Balance-nya menyala."
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
        # Tanggal hangus **tidak** dihitung ulang saat update. Ia
        # dibekukan saat dokumen dibuat, dan mengubah policy hari ini
        # tidak boleh memundurkan hak yang sudah dikabarkan ke pegawai.
        # Yang mau menggesernya mengetiknya sendiri, dan itu terlihat
        # di jejak audit.
        #
        # Tahunnya diturunkan ulang hanya kalau tanggal berlakunya ikut
        # diubah dan tahunnya sendiri tidak disebut: kartu tujuan harus
        # tetap sebaris dengan tanggalnya.
        cls.assert_uses_balance(data, instance=instance)

        if "opening_date" in data and not data.get("year"):
            data.pop("year", None)

            data = cls.apply_year(data)

        return data

    # ------------------------------------------------------------------
    # Sinkronisasi ke kartu saldo
    # ------------------------------------------------------------------

    @classmethod
    def sync_balance(
        cls,
        *,
        employee,
        leave_type,
        year: int | None,
        user=None,
    ) -> LeaveBalance | None:
        """
        Menulis ulang kantong saldo awal pada satu kartu.

        Kartunya dibuat kalau belum ada. Itu disengaja: saldo migrasi
        lazim menyangkut jenis cuti yang belum punya policy, dan
        `LeaveBalanceGenerator` memang hanya menerbitkan kartu untuk
        jenis cuti yang punya aturan. Tanpa ini, angka yang sudah
        diimpor tidak muncul di layar mana pun.
        """
        if employee is None or leave_type is None or year is None:
            return None

        # **Hanya yang sudah di-post.** Draft terbaca di layar dan bisa
        # dibetulkan, tapi tidak menyumbang satu angka pun ke kartu —
        # itulah yang membuat langkah Review punya arti. Baris yang
        # di-unpost otomatis keluar lagi dari sini, karena angkanya
        # dijumlah ulang dan bukan ditambah inkremental.
        rows = (
            LeaveOpeningBalance.objects
            .filter(
                employee=employee,
                leave_type=leave_type,
                year=year,
                status=LeaveOpeningStatus.POSTED,
                is_deleted=False,
            )
        )

        total = Decimal("0.0")
        expires_at = None

        for row in rows:
            total += row.days or Decimal("0.0")

            # Constraint membuat baris aktifnya cuma satu per pasangan
            # (pegawai, jenis cuti), jadi ini praktis selalu satu baris.
            # Kalau suatu saat batas itu dilonggarkan, yang paling awal
            # yang menentukan — masa berlaku tidak boleh ikut mundur
            # gara-gara ada baris baru ditambahkan.
            if row.expires_at and (
                expires_at is None or row.expires_at < expires_at
            ):
                expires_at = row.expires_at

        balance = (
            LeaveBalance.objects
            .filter(
                employee=employee,
                leave_type=leave_type,
                year=year,
                is_deleted=False,
            )
            .first()
        )

        if balance is None:
            if not total and expires_at is None:
                return None

            return LeaveBalance.objects.create(
                employee=employee,
                leave_type=leave_type,
                year=year,
                opening_balance=total,
                opening_expires_at=expires_at,
                created_by=user,
            )

        if (
            balance.opening_balance == total
            and balance.opening_expires_at == expires_at
        ):
            return balance

        balance.opening_balance = total
        balance.opening_expires_at = expires_at
        balance.updated_by = user

        # `update_fields` sengaja sempit: kartu saldo disentuh beberapa
        # penulis sekaligus (generator, carry over, perhitungan ulang
        # pemakaian), dan menyimpan seluruh baris di sini bisa menimpa
        # angka yang baru saja ditulis salah satunya.
        balance.save(
            update_fields=[
                "opening_balance",
                "opening_expires_at",
                "updated_by",
                "updated_at",
            ],
        )

        return balance

    @classmethod
    def sync_entitlement(
        cls,
        *,
        employee,
        leave_type,
        year: int | None,
        user=None,
    ) -> LeaveBalance | None:
        """
        Menulis ulang jatah tahun itu sesudah dokumennya berubah.

        Inilah yang membuat Post cukup satu langkah. Tahun yang sudah
        punya saldo awal ter-post tidak lagi menerbitkan jatah dari
        policy (`LeaveEntitlementCalculator.replaced_by_opening`), jadi
        Post harus **menuliskan nol itu** ke kartunya — kalau tidak,
        kartu yang jatahnya sudah pernah terbit lebih dulu (mis. lewat
        `EmploymentService.sync_leave_balances` saat kartu pegawainya
        disunting) akan menjumlahkan 12 + 7 dan berbunyi 19. Unpost
        mengembalikannya, lewat jalur yang sama persis.

        Ini juga yang membuat urutan langkahnya bebas: Post boleh
        dijalankan sebelum atau sesudah jatah tahun itu pernah dihitung
        siapa pun, dan hasilnya sama.

        Jenis cuti yang **tidak** punya policy dilewati, bukan ditulis
        nol: `LeaveBalanceGenerator` pun tidak pernah menerbitkan jatah
        untuknya, jadi menyentuh angkanya di sini berarti kartu saldo
        migrasi punya dua penulis yang saling menimpa.
        """
        if employee is None or leave_type is None or year is None:
            return None

        from apps.hr.api.leave.entitlement import (
            LeaveEntitlementCalculator,
        )

        entitlement = LeaveEntitlementCalculator.for_employee(
            employee=employee,
            leave_type=leave_type,
            year=year,
        )

        if not entitlement.has_policy:
            return None

        # Aturan yang tidak bersaldo tidak punya kartu untuk ditulisi.
        # Diperiksa walau `assert_uses_balance` sudah menolak di jalur
        # tulis: dokumen lama bisa saja dibuat sebelum saklarnya
        # dimatikan, dan yang dijalankan di sini adalah sinkronisasi,
        # bukan pembuatan.
        if not entitlement.issues_balance:
            return None

        balance = (
            LeaveBalance.objects
            .filter(
                employee=employee,
                leave_type=leave_type,
                year=year,
                is_deleted=False,
            )
            .first()
        )

        if balance is None or balance.entitlement == entitlement.days:
            return balance

        balance.entitlement = entitlement.days
        balance.updated_by = user

        # `update_fields` sempit, alasan yang sama dengan
        # `sync_balance`: kartu ini punya beberapa penulis dan
        # menyimpan seluruh barisnya bisa menimpa angka yang baru saja
        # ditulis salah satunya.
        balance.save(
            update_fields=[
                "entitlement",
                "updated_by",
                "updated_at",
            ],
        )

        return balance

    @classmethod
    def sync_for(cls, instance, *, user=None) -> None:
        cls.sync_balance(
            employee=instance.employee,
            leave_type=instance.leave_type,
            year=instance.year,
            user=user,
        )

        # Sesudah kantong saldo awalnya ditulis, bukan sebelum:
        # `sync_balance` yang membuat kartunya kalau belum ada, dan
        # jatah tidak bisa ditulis ke kartu yang belum berdiri.
        cls.sync_entitlement(
            employee=instance.employee,
            leave_type=instance.leave_type,
            year=instance.year,
            user=user,
        )

    # ------------------------------------------------------------------
    # Review -> Post
    # ------------------------------------------------------------------

    @classmethod
    def assert_editable(cls, instance) -> None:
        """
        Baris yang sudah di-post tidak disunting di tempat.

        Angkanya sudah menempel di kartu cuti orang dan sudah dibaca
        pengajuan cuti yang berjalan di atasnya; mengubahnya tanpa jejak
        berarti saldo seseorang bergeser tanpa satu peristiwa pun yang
        bisa ditunjuk. Tarik dulu (Unpost) — dan itu tindakan yang
        terlihat, tercatat, dan bisa dijelaskan.
        """
        if instance is not None and instance.is_posted:
            raise ValidationError(
                "Saldo awal ini sudah di-post dan angkanya sudah "
                "berlaku di kartu cuti. Tarik dulu lewat Unpost kalau "
                "memang perlu dibetulkan.",
            )

    @classmethod
    def assert_postable(cls, instance) -> None:
        if instance.is_posted:
            raise ValidationError("Saldo awal ini sudah di-post.")

        if instance.days is None or instance.days < 0:
            raise ValidationError(
                "Saldo awal tidak boleh negatif.",
            )

    @classmethod
    @transaction.atomic
    def post(cls, *, instance, user=None):
        """
        Menyatakan angka ini berlaku, lalu menerbitkan kartu saldonya.

        Inilah langkah yang membuat saldo awal jadi **saldo pegawai**.
        Sebelum ini barisnya cuma catatan; sesudahnya ia muncul di kartu
        cuti, ikut dihitung `remaining`, dan bisa dipakai mengajukan
        cuti.

        Rantainya: dokumen → transaksi saldo awal → kartu saldo. Yang
        **jadi** transaksinya adalah baris ini sendiri begitu statusnya
        POSTED — `posted_at` dan `posted_by` waktu dan pelakunya — bukan
        satu baris di tabel ledger tersendiri. Itu keputusan sadar, dan
        alasannya sama dengan yang berlaku di seluruh codebase ini:
        kantong di `LeaveBalance` **dijumlah ulang** dari sumbernya
        (`used` dari catatan cuti, `opening_balance` dari dokumen ini,
        `helpful_count` dari baris feedback). Ledger terpisah berarti
        dua sumber untuk angka yang sama — dan yang satu diam-diam
        hanyut dari yang lain. Kalau nanti pemakaian cuti perlu ditelusuri
        per transaksi, yang ditambah satu ledger untuk **seluruh** mutasi
        cuti, bukan satu tabel khusus saldo awal.
        """
        cls.assert_postable(instance)

        instance.status = LeaveOpeningStatus.POSTED
        instance.posted_at = timezone.now()
        instance.posted_by = user
        instance.updated_by = user

        instance.save(
            update_fields=[
                "status",
                "posted_at",
                "posted_by",
                "updated_by",
                "updated_at",
            ],
        )

        cls._audit(
            instance=instance,
            action="update",
            user=user,
            before={"status": LeaveOpeningStatus.DRAFT},
            after={"status": LeaveOpeningStatus.POSTED},
        )

        cls.sync_for(instance, user=user)

        return instance

    @classmethod
    @transaction.atomic
    def unpost(cls, *, instance, user=None):
        """
        Menarik kembali angkanya dari kartu saldo.

        Tidak dilarang walau cutinya sudah dipakai: yang ditarik cuma
        pemberiannya, dan pemakaian tetap tercatat sebagai pemakaian —
        kartunya boleh jadi minus, dan `advance_used` memang ada untuk
        menjelaskan keadaan itu. Melarangnya justru mengunci HR pada
        angka salah yang tidak bisa dibetulkan dari layar mana pun.
        """
        if not instance.is_posted:
            raise ValidationError("Saldo awal ini masih draft.")

        instance.status = LeaveOpeningStatus.DRAFT
        instance.posted_at = None
        instance.posted_by = None
        instance.updated_by = user

        instance.save(
            update_fields=[
                "status",
                "posted_at",
                "posted_by",
                "updated_by",
                "updated_at",
            ],
        )

        cls._audit(
            instance=instance,
            action="update",
            user=user,
            before={"status": LeaveOpeningStatus.POSTED},
            after={"status": LeaveOpeningStatus.DRAFT},
        )

        # Sesudah statusnya turun, bukan sebelum: `sync_for` membaca
        # ulang baris yang POSTED dari database, jadi memanggilnya lebih
        # dulu akan menuliskan kembali angka yang sedang ditarik.
        cls.sync_for(instance, user=user)

        return instance

    @classmethod
    def post_many(cls, *, queryset, user=None) -> dict:
        """
        Posting massal — jalur yang sebenarnya dipakai saat go-live.

        Satu batch migrasi berisi ratusan baris, dan menekan Post satu
        per satu bukan alur yang bisa dijalankan siapa pun.

        Tiap baris di savepoint sendiri: satu pegawai yang datanya
        bermasalah tidak boleh membatalkan dua ratus sembilan puluh
        sembilan lainnya. Pola yang sama dengan commit per baris di
        Roster Setup.
        """
        posted = 0
        skipped = 0
        failures: list[dict] = []

        for instance in queryset:
            if instance.is_posted:
                skipped += 1
                continue

            try:
                with transaction.atomic():
                    cls.post(instance=instance, user=user)

                posted += 1
            except Exception as exc:  # noqa: BLE001
                failures.append(
                    {
                        "id": instance.pk,
                        "employee": getattr(
                            instance.employee,
                            "employee_number",
                            None,
                        ),
                        "message": str(exc),
                    },
                )

        return {
            "posted": posted,
            "skipped": skipped,
            "failed": len(failures),
            "failures": failures,
        }

    # ------------------------------------------------------------------
    # Hook
    # ------------------------------------------------------------------

    @classmethod
    def after_create(cls, *, instance, user=None, **kwargs):
        instance = super().after_create(
            instance=instance,
            user=user,
            **kwargs,
        )

        cls.sync_for(instance, user=user)

        return instance

    @classmethod
    @transaction.atomic
    def update(cls, *, instance, data: dict[str, Any], user=None, **kwargs):
        # Kombinasi sebelum perubahan ikut disinkronkan — memindahkan
        # dokumen ke jenis cuti atau tahun lain harus mengosongkan
        # kantong di kartu yang ditinggalkannya. Kalau tidak, angkanya
        # tertinggal di dua tempat dan yang membacanya menghitung dobel.
        # Menyunting baris yang sudah berlaku ditolak di sini, bukan di
        # serializer: importer dan perintah manajemen menulis lewat
        # service yang sama, dan penjagaan yang cuma ada di serializer
        # tidak pernah kelewatan mereka.
        cls.assert_editable(instance)

        previous = (
            instance.employee,
            instance.leave_type,
            instance.year,
        )

        instance = super().update(
            instance=instance,
            data=data,
            user=user,
            **kwargs,
        )

        if previous != (instance.employee, instance.leave_type, instance.year):
            cls.sync_balance(
                employee=previous[0],
                leave_type=previous[1],
                year=previous[2],
                user=user,
            )

            # Kartu yang ditinggalkan harus dapat jatahnya kembali —
            # dokumennya sudah tidak menggantikan apa pun di sana.
            cls.sync_entitlement(
                employee=previous[0],
                leave_type=previous[1],
                year=previous[2],
                user=user,
            )

        cls.sync_for(instance, user=user)

        return instance

    @classmethod
    def after_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        super().after_soft_delete(
            instance=instance,
            user=user,
            **kwargs,
        )

        cls.sync_for(instance, user=user)

    @classmethod
    @transaction.atomic
    def restore(cls, *, instance, user=None, **kwargs):
        instance = super().restore(
            instance=instance,
            user=user,
            **kwargs,
        )

        cls.sync_for(instance, user=user)

        return instance
