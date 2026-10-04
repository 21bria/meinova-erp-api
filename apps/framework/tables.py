"""
Paginasi sisi server untuk widget `table` di dashboard/laporan.

Ada di framework, bukan di `apps/reports`, karena pertanyaannya sama
untuk setiap laporan yang akan menyusul (Payroll, SCM, Finance): halaman
ke berapa, berapa baris, dan apa yang dicari. Menuliskannya ulang per
laporan berarti tiap laporan punya nama parameter dan batas ukurannya
sendiri — dan yang paling mahal bukan duplikasinya, melainkan laporan
kelima yang diam-diam menerima `?page_size=100000`.

**Yang dipaginasi hanya tabelnya.** KPI, chart, dan baris Total tetap
dihitung dari **seluruh** dataset yang lolos filter. Pindah halaman
karena itu tidak boleh mengubah satu angka pun di luar tabel — kalau
bisa, angka ringkasan berhenti menjadi ringkasan dan menjadi jumlah
halaman yang kebetulan sedang terbuka.

`search` juga hanya menyentuh tabel. Ia bukan filter laporan: filter
laporan sudah punya tempatnya sendiri di `filters` dan ikut mengubah
KPI. Kotak cari di kepala tabel menjawab pertanyaan yang berbeda —
"di mana baris orang ini" — dan menjawabnya dengan ikut memindahkan KPI
berarti pemakainya kehilangan pembandingnya tepat saat ia butuh.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any, Callable, Mapping, Sequence


DEFAULT_PAGE_SIZE = 25

# Pilihan yang boleh diminta. Bukan sekadar saran untuk dropdown:
# `from_request` menolak angka di luar daftar ini dan jatuh ke bawaan,
# jadi tidak ada jalan meminta seluruh tenant dalam satu halaman lewat
# query string.
PAGE_SIZE_OPTIONS: tuple[int, ...] = (25, 50, 100)


@dataclass(frozen=True)
class TablePage:
    """Halaman yang sedang diminta, sudah dibersihkan dan dibatasi."""

    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    search: str = ""

    # ------------------------------------------------------------------
    # Pembacaan
    # ------------------------------------------------------------------

    @classmethod
    def from_request(
        cls,
        request,
        widget: Mapping[str, Any] | None = None,
    ) -> "TablePage":
        """
        `?page=&page_size=&search=`, dibatasi oleh deklarasi widget-nya.

        Nilai yang tidak masuk akal jatuh ke bawaan alih-alih membalas
        error — aturan yang sama dengan `BaseDashboardAPIView.get_period`:
        satu parameter salah ketik tidak boleh mematikan seluruh halaman.
        """
        widget = widget or {}

        params = getattr(request, "query_params", None) or {}

        options = cls.options_for(widget)

        default_size = widget.get("page_size") or DEFAULT_PAGE_SIZE

        if default_size not in options:
            default_size = options[0]

        return cls(
            page=cls._positive(params.get("page"), fallback=1),
            page_size=cls._one_of(
                params.get("page_size"),
                allowed=options,
                fallback=default_size,
            ),
            search=str(params.get("search") or "").strip(),
        )

    @staticmethod
    def options_for(widget: Mapping[str, Any] | None) -> tuple[int, ...]:
        declared = (widget or {}).get("page_size_options")

        if not declared:
            return PAGE_SIZE_OPTIONS

        return tuple(int(item) for item in declared)

    @staticmethod
    def _positive(raw, *, fallback: int) -> int:
        value = str(raw or "").strip()

        if not value.isdigit():
            return fallback

        # `?page=0` jatuh ke halaman pertama, bukan ke offset negatif
        # yang mengiris daftar dari belakang tanpa ada yang menyadarinya.
        return max(int(value), 1)

    @staticmethod
    def _one_of(raw, *, allowed: Sequence[int], fallback: int) -> int:
        value = str(raw or "").strip()

        if not value.isdigit():
            return fallback

        number = int(value)

        return number if number in allowed else fallback

    # ------------------------------------------------------------------
    # Pemakaian
    # ------------------------------------------------------------------

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    def matching(
        self,
        rows: Sequence[Any],
        *,
        text: Callable[[Any], str],
    ) -> list[Any]:
        """Baris yang cocok dengan kotak cari; tanpa cari = semuanya."""
        if not self.search:
            return list(rows)

        needle = self.search.casefold()

        return [row for row in rows if needle in text(row).casefold()]

    def slice(self, rows: Sequence[Any]) -> list[Any]:
        return list(rows[self.offset:self.offset + self.page_size])

    def envelope(
        self,
        *,
        items: list[Any],
        matched: int,
        total: int,
        **extra: Any,
    ) -> dict:
        """
        `total` adalah seluruh baris yang lolos filter laporan;
        `matched` adalah yang lolos kotak cari. Keduanya dikirim karena
        keduanya berbeda arti: yang pertama dipakai memberi tahu bahwa
        KPI menghitung lebih banyak orang daripada yang sedang terlihat,
        yang kedua dipakai menghitung jumlah halaman.
        """
        return {
            "items": items,
            "total": total,
            "matched": matched,
            "page": self.page,
            "page_size": self.page_size,
            "page_count": max(ceil(matched / self.page_size), 1),
            "search": self.search,
            **extra,
        }
