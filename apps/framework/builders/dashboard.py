"""
Builder DSL untuk schema dashboard per modul (`schema_type="dashboard"`).

Bedanya dengan `apps.administration.api.dashboard`: yang di sana adalah
dashboard *home* — daftar aplikasi favorit dan tata letak widget yang
bisa digeser tiap user, datanya disimpan di database. Yang di sini
adalah dashboard *modul* (HR, Payroll, Finance): susunannya ditentukan
kode, sama untuk semua orang, dan datanya dihitung dari transaksi.

Satu widget = satu key. Key itu yang dipakai `BaseDashboardAPIView`
untuk mencari resolver-nya (`resolve_<key>`), jadi schema tetap menjadi
satu-satunya sumber kebenaran tentang widget apa yang ada.

`span` memakai grid 12 kolom, ikut konvensi yang lazim di frontend.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from apps.framework.periods import DEFAULT_PERIOD_MODES


FieldConfig = dict[str, Any]


def _clean(data: Mapping[str, Any]) -> FieldConfig:
    return {k: v for k, v in data.items() if v is not None}


def widget(
    key: str,
    *,
    widget_type: str,
    label: str | None = None,
    description: str | None = None,
    span: int = 12,
    order: int = 0,
    permission: str | None = None,
    **extra: Any,
) -> FieldConfig:
    return _clean(
        {
            "key": key,
            "type": widget_type,
            "label": label,
            "description": description,
            "span": span,
            "order": order,
            "permission": permission,
            **extra,
        }
    )


def stat(
    key: str,
    *,
    label: str,
    icon: str | None = None,
    format: str = "number",
    currency_field: str | None = None,
    precision: int | None = None,
    trend: bool = True,
    span: int = 2,
    order: int = 0,
    **extra: Any,
) -> FieldConfig:
    """
    Kartu KPI. `format` menentukan cara frontend merender angkanya:
    "number" | "percent" | "currency" | "duration" | "text".

    `trend=True` berarti resolver ikut mengirim `trend`
    ({value, direction, period}); frontend menyembunyikan bagian itu
    kalau nilainya tidak ada — jadi periode pembanding yang kosong
    tidak merusak tampilan.
    """
    return widget(
        key,
        widget_type="stat",
        label=label,
        icon=icon,
        format=format,
        currency_field=currency_field,
        precision=precision,
        trend=trend,
        span=span,
        order=order,
        **extra,
    )


def chart(
    key: str,
    *,
    label: str,
    chart: str,
    description: str | None = None,
    x_label: str | None = None,
    y_label: str | None = None,
    y_format: str = "number",
    stacked: bool | None = None,
    summary: bool | None = None,
    span: int = 8,
    order: int = 0,
    **extra: Any,
) -> FieldConfig:
    """
    `chart`: "line" | "bar" | "donut" | "area".

    Resolver mengembalikan `{"series": [{"label", "value"}], ...}`;
    untuk donut tiap titik boleh membawa `percentage` dan `color`.

    `summary=False` mematikan angka ringkasan di kanan judul (Total
    untuk chart distribusi, nilai titik terakhir untuk chart tren).
    Dipakai chart yang jumlah deretnya memang **bukan angka** —
    Komposisi Payroll memuat sisi penghasilan dan sisi potongan
    sekaligus, dan jumlah keduanya bukan gross, bukan net, bukan biaya.
    Tercetak besar di sebelah judul, ia terbaca sebagai angka utama
    kartunya.

    Dikosongkan = ringkasannya tampil, sama dengan perilaku sebelum
    kunci ini ada — `_clean` membuang nilai None, jadi schema yang
    tidak menyebutkannya tidak berubah sebyte pun.
    """
    return widget(
        key,
        widget_type="chart",
        label=label,
        description=description,
        chart=chart,
        x_label=x_label,
        y_label=y_label,
        y_format=y_format,
        stacked=stacked,
        summary=summary,
        span=span,
        order=order,
        **extra,
    )


def line(key: str, **kwargs: Any) -> FieldConfig:
    return chart(key, chart="line", **kwargs)


def bar(key: str, **kwargs: Any) -> FieldConfig:
    return chart(key, chart="bar", **kwargs)


def donut(key: str, *, span: int = 4, **kwargs: Any) -> FieldConfig:
    return chart(key, chart="donut", span=span, **kwargs)


def listing(
    key: str,
    *,
    label: str,
    columns: Sequence[Mapping[str, Any]] | None = None,
    empty_text: str | None = None,
    link: str | None = None,
    limit: int | None = None,
    span: int = 4,
    order: int = 0,
    **extra: Any,
) -> FieldConfig:
    """
    Daftar ringkas (mis. "Cuti Terbaru"). `columns` mendeskripsikan
    kolom yang dirender; `link` adalah tujuan tombol "Lihat Semua".
    """
    return widget(
        key,
        widget_type="list",
        label=label,
        columns=list(columns) if columns else None,
        empty_text=empty_text,
        link=link,
        limit=limit,
        span=span,
        order=order,
        **extra,
    )


def table(
    key: str,
    *,
    label: str,
    columns: Sequence[Mapping[str, Any]] | None = None,
    description: str | None = None,
    empty_text: str | None = None,
    sticky_columns: int = 1,
    page_size: int | None = None,
    page_size_options: Sequence[int] | None = None,
    searchable: bool = False,
    search_placeholder: str | None = None,
    search_placeholder_key: str | None = None,
    span: int = 12,
    order: int = 0,
    **extra: Any,
) -> FieldConfig:
    """
    Tabel lebar yang digulir mendatar — bentuk laporan, bukan dashboard.

    Bedanya dengan `listing()` bukan sekadar jumlah kolom. `listing()`
    memampatkan barisnya jadi judul + keterangan + beberapa angka di
    kanan karena kartunya sempit; laporan justru dibaca **per kolom**,
    dan memampatkannya menghilangkan tepat hal yang dicari pembacanya.

    `sticky_columns` adalah jumlah kolom pertama yang ikut terkunci saat
    digeser. Nol kolom terkunci membuat pembacanya kehilangan nama
    pegawai begitu tabel digeser ke Total OT — dan angka tanpa nama
    tidak berarti apa-apa.

    Kolom boleh membawa `drilldown` (nama metrik) yang membuat selnya
    bisa ditekan untuk membuka rincian sumbernya.

    `page_size` menyalakan paginasi **sisi server**; ukurannya dibatasi
    ke `page_size_options` (lihat `apps.framework.tables.TablePage`).
    Yang dipaginasi hanya tabelnya — KPI, chart, dan baris Total tetap
    dihitung dari seluruh dataset yang lolos filter, jadi pindah halaman
    tidak menggeser satu angka pun di luar tabel.
    """
    return widget(
        key,
        widget_type="table",
        label=label,
        description=description,
        columns=list(columns) if columns else None,
        empty_text=empty_text,
        sticky_columns=sticky_columns,
        page_size=page_size,
        page_size_options=(
            list(page_size_options) if page_size_options else None
        ),
        searchable=searchable or None,
        search_placeholder=search_placeholder,
        # Kode konteks pencarian (`employee`, `organization`), bukan
        # kalimatnya: kalimatnya tinggal di katalog frontend, dan tabel
        # dashboard tetap generik. `search_placeholder` tetap dikirim
        # sebagai teks cadangan untuk schema yang belum menyebut kode.
        search_placeholder_key=search_placeholder_key,
        span=span,
        order=order,
        **extra,
    )


def column(
    key: str,
    *,
    label: str,
    format: str = "text",
    **extra: Any,
) -> FieldConfig:
    return _clean(
        {
            "key": key,
            "label": label,
            "format": format,
            **extra,
        }
    )


def period_filter(
    *,
    key: str = "period",
    label: str = "Period",
    mode: str = "month",
    modes: Sequence[str] | None = None,
    default: str = "current",
    **extra: Any,
) -> FieldConfig:
    """
    Filter periode di kanan atas dashboard.

    `modes` adalah satuan yang boleh dipilih user — "day" | "week" |
    "month" | "quarter" | "year" | "custom" — dan `mode` adalah yang
    aktif saat halaman pertama dibuka. Keduanya ditegakkan di backend
    juga (`BaseDashboardAPIView.get_period`), jadi mode yang tidak
    terdaftar di sini tidak bisa dipaksa lewat query string.

    Apa pun modenya, resolver hanya melihat `period["start"]` dan
    `period["end"]` — tidak perlu tahu user memilih minggu atau bulan.
    """
    return _clean(
        {
            "key": key,
            "type": "period",
            "label": label,
            "mode": mode,
            "modes": (
                list(modes)
                if modes
                else list(DEFAULT_PERIOD_MODES)
            ),
            "default": default,
            **extra,
        }
    )


def lookup_filter(
    key: str,
    *,
    label: str,
    lookup_endpoint: str,
    depends_on: str | None = None,
    lookup_params: Mapping[str, Any] | None = None,
    multiple: bool = False,
    placement: str = "quick",
    self_filter: str | None = None,
    self_filter_label: str | None = None,
    **extra: Any,
) -> FieldConfig:
    """
    `placement` — "quick" atau "advanced", dialek yang sama dengan
    filter CRUD (`framework/builders/filters/types.ts`, `FilterPlacement`).
    Yang "quick" berdiri di kepala halaman; sisanya masuk panel Advanced
    Filter, dan panelnya sendiri baru muncul kalau ada yang mengisinya.

    Bawaannya **"quick"** supaya dashboard yang sudah ada tidak berubah
    tampilannya gara-gara kunci baru ini: sebelum ada `placement`,
    seluruh filter memang berdiri di kepala halaman. Yang memindahkan
    filter ke panel adalah schema yang menyebutnya sendiri — laporan
    berfilter sembilan seperti HR Period Summary, di mana baris filter
    yang tidak dilipat memakan seluruh kepala halaman dan menenggelamkan
    dua filter yang benar-benar dipakai tiap hari.

    `multiple=True` menjadikannya daftar centang, dan nilainya dikirim
    sebagai `?key=1,2,3`. Dipakai saat pertanyaannya "bagaimana kedua
    lokasi ini" — dropdown satu-pilihan memaksa memilih antara satu
    lokasi atau seluruh tenant, tidak ada di antaranya.

    Tidak ada yang dicentang = **tanpa penyaringan**, bukan tanpa hasil.
    Aturan yang sama dengan menu dan cakupan data di sistem ini.

    `self_filter` memasang tombol pintas satu-tekan yang mengisi filter
    ini dengan nilai dari profil penggunanya, ditulis dengan dialek
    `$me.<jalur>` yang **sudah dipakai schema form** (`$me.placement.
    company`, `$me.data_scope.values.location`). Satu tombol melayani
    semua tenant: yang ditempatkan di Jakarta menekannya dan mendapat
    Jakarta, yang di Gebe mendapat Gebe — tidak ada nama lokasi yang
    ditulis di kode, dan itu penting karena "HO" adalah sebutan yang
    berbeda-beda per klien.

    **Tidak menyala sendiri saat halaman dibuka.** Angka pertama yang
    dilihat orang harus angka utuh; dashboard yang diam-diam sudah
    tersaring membuat pemegang akses penuh membaca sebagian sebagai
    keseluruhan, dan tidak ada di layar yang memberi tahu bedanya.
    """
    return _clean(
        {
            "key": key,
            "type": "lookup",
            "label": label,
            "lookup_endpoint": lookup_endpoint,
            "depends_on": depends_on,
            "lookup_params": dict(lookup_params) if lookup_params else None,
            "multiple": multiple or None,
            "placement": placement,
            "self_filter": self_filter,
            "self_filter_label": self_filter_label,
            **extra,
        }
    )


def schema(
    *,
    module: str,
    label: str,
    endpoint: str,
    widgets: Sequence[Mapping[str, Any]],
    filters: Sequence[Mapping[str, Any]] | None = None,
    title: str | None = None,
    description: str | None = None,
    columns: int = 12,
    **extra: Any,
) -> FieldConfig:
    return _clean(
        {
            "module": module,
            "name": extra.pop("name", None) or label.replace(" ", ""),
            "label": label,
            "endpoint": endpoint,
            "schema_type": "dashboard",
            "title": title or label,
            "description": description,
            "columns": columns,
            "filters": list(filters) if filters else [],
            "widgets": sorted(
                (dict(item) for item in widgets),
                key=lambda item: item.get("order", 0),
            ),
            **extra,
        }
    )
