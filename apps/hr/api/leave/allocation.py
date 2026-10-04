"""
Cuti mana menggerus kantong mana.

Kartu saldo punya **tiga kantong** yang lahir dari tempat berbeda:

* `opening_balance` — saldo dari sistem lama, titik awal migrasi
* `carried_over`   — sisa tahun lalu yang dibawa masuk
* `entitlement`    — jatah tahun berjalan menurut policy

Selama `used` cuma satu angka untuk seluruh kartu, "yang terpakai itu
kantong yang mana" tidak bisa dijawab — dan tanpa jawaban itu,
penghangusan tidak bisa dieksekusi sama sekali: tidak ada cara
membedakan bawaan yang **belum** terpakai (memang hangus) dari bawaan
yang sudah dipakai bulan Maret (tidak ada yang perlu dihanguskan).
Berkas ini yang menutupnya.

Aturannya: **yang paling cepat hangus dipakai lebih dulu.**
Kalau dibalik, setiap orang kehilangan bawaannya walau cutinya banyak,
dan tidak ada yang bisa menjelaskan kenapa.

Dihitung ulang dari nol tiap kali ada cuti berubah, sama seperti
`recalculate_used` — bukan ditambah/dikurangi inkremental. Penjumlahan
ulang tidak bisa hanyut.

**Fungsi murni, tanpa satu pun query.** Itu properti yang harus dijaga:
ia dipakai perhitungan ulang, pratinjau di form, dan perintah
penghangusan — ketiganya harus memakai jalan yang sama, dan pengujiannya
tidak boleh butuh tenant. Pola yang sama dengan `RosterCalculationService`
dan `RotationPeriodGenerator`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


ZERO = Decimal("0.0")


# Kantong, dari yang paling tua asal-usulnya. Dipakai sebagai pemecah
# seri saat dua kantong hangus di tanggal yang sama — bukan sebagai
# urutan utama: yang menentukan tetap tanggal hangusnya.
POCKET_OPENING = "opening"
POCKET_CARRIED_OVER = "carried_over"
POCKET_ENTITLEMENT = "entitlement"

POCKET_ORDER = {
    POCKET_OPENING: 0,
    POCKET_CARRIED_OVER: 1,
    POCKET_ENTITLEMENT: 2,
}


@dataclass(frozen=True)
class Pocket:
    """Satu kantong beserta masa berlakunya."""

    key: str
    days: Decimal

    # Tanggal hangus. `None` = tidak pernah hangus, dan itu yang paling
    # lazim — `carry_over_expiry_months` bawaannya kosong.
    expires_at: date | None = None

    def usable_on(self, day: date | None) -> bool:
        """
        Masih boleh dipakai untuk cuti yang mulai pada `day`.

        Batasnya **eksklusif**, sejajar dengan syarat penghangusan
        (`expires_at <= today` berarti sudah hangus). Kalau di sini
        inklusif, cuti yang mulai tepat di tanggal hangus akan
        menggerus kantong yang pada hari itu sudah tidak ada.
        """
        if self.expires_at is None or day is None:
            return True

        return day < self.expires_at


@dataclass(frozen=True)
class Claim:
    """Satu catatan cuti yang memotong saldo."""

    days: Decimal
    start_date: date | None = None
    reference: object = None


@dataclass
class Allocation:
    # Berapa hari yang tergerus dari tiap kantong.
    consumed: dict[str, Decimal] = field(default_factory=dict)

    # Bagian pemakaian yang **tidak** punya kantong — cuti dibayar di
    # muka. Disimpan terpisah supaya saldo minus punya penjelasan:
    # tanpa ini, kartu bersaldo −3 tidak bisa dibedakan dari kartu yang
    # angka jatahnya salah hitung.
    advance: Decimal = ZERO

    # Bagian pemakaian yang jatuh **setelah** kantongnya hangus. Ikut
    # dihitung sebagai `advance`, tapi sebabnya berbeda dan itu yang
    # ditanyakan orang.
    expired_shortfall: Decimal = ZERO

    def taken(self, key: str) -> Decimal:
        return self.consumed.get(key, ZERO)

    def remaining_of(self, pocket: Pocket) -> Decimal:
        left = (pocket.days or ZERO) - self.taken(pocket.key)

        return left if left > ZERO else ZERO


def allocate(
    *,
    pockets: list[Pocket],
    claims: list[Claim],
) -> Allocation:
    """
    Membagi pemakaian ke kantong-kantongnya.

    Urutan cuti **wajib** `(start_date, id)` di sisi pemanggil. Kalau
    diurutkan id saja, mengoreksi tanggal satu cuti lama akan memindahkan
    kantong seluruh cuti sesudahnya — dan jumlah hari hangus seseorang
    berubah tanpa ada yang menyentuh datanya.
    """
    result = Allocation()

    # Salinan sisa tiap kantong; `pockets` sendiri tidak disentuh supaya
    # pemanggil boleh memakainya lagi.
    left = {
        pocket.key: (pocket.days or ZERO)
        for pocket in pockets
    }

    ordered = sorted(
        pockets,
        key=lambda item: (
            # Yang paling cepat hangus lebih dulu. Yang tidak pernah
            # hangus paling belakang — memakainya duluan berarti
            # membuang kantong yang justru punya tenggat.
            item.expires_at is None,
            item.expires_at or date.max,
            POCKET_ORDER.get(item.key, 99),
        ),
    )

    for claim in claims:
        outstanding = claim.days or ZERO

        if outstanding <= ZERO:
            # Nol itu sah: pegawai roster yang cuti saat blok off-nya
            # memang tidak memotong apa pun.
            continue

        blocked = ZERO

        for pocket in ordered:
            if outstanding <= ZERO:
                break

            available = left.get(pocket.key, ZERO)

            if available <= ZERO:
                continue

            if not pocket.usable_on(claim.start_date):
                # Kantongnya masih bersisa tapi sudah hangus saat cuti
                # ini diambil. Dicatat supaya kekurangannya bisa
                # dijelaskan, bukan dilewati diam-diam.
                blocked += available

                continue

            take = available if available < outstanding else outstanding

            left[pocket.key] = available - take
            result.consumed[pocket.key] = result.taken(pocket.key) + take

            outstanding -= take

        if outstanding > ZERO:
            result.advance += outstanding

            if blocked > ZERO:
                shortfall = (
                    blocked
                    if blocked < outstanding
                    else outstanding
                )

                result.expired_shortfall += shortfall

    return result


def pockets_from_balance(balance) -> list[Pocket]:
    """
    Tiga kantong sebuah kartu saldo, apa adanya.

    `adjustment` **tidak** jadi kantong tersendiri: ia boleh negatif,
    dan koreksi manual memang dimaksudkan menggeser total — bukan
    menciptakan hak yang punya masa berlaku sendiri. Ia tetap ikut di
    `remaining`, cuma tidak ikut dialokasikan.
    """
    return [
        Pocket(
            key=POCKET_OPENING,
            days=balance.opening_balance or ZERO,
            expires_at=balance.opening_expires_at,
        ),
        Pocket(
            key=POCKET_CARRIED_OVER,
            days=balance.carried_over or ZERO,
            expires_at=balance.carried_over_expires_at,
        ),
        Pocket(
            key=POCKET_ENTITLEMENT,
            days=balance.entitlement or ZERO,
            expires_at=None,
        ),
    ]


def claims_from_leaves(leaves) -> list[Claim]:
    """
    Catatan cuti jadi klaim, urut `(start_date, id)`.

    Pengurutannya di sini, bukan diserahkan ke pemanggil: urutan itu
    bagian dari aturannya, dan satu pemanggil yang lupa mengurutkan
    menghasilkan angka hangus yang berbeda tanpa ada yang menyadarinya.
    """
    ordered = sorted(
        leaves,
        key=lambda leave: (
            leave.start_date or date.min,
            leave.pk or 0,
        ),
    )

    return [
        Claim(
            days=leave.total_days or ZERO,
            start_date=leave.start_date,
            reference=leave,
        )
        for leave in ordered
    ]
