"""
Tombol pada layar resource.

Tiga jenis, dan yang membedakan **siapa yang menjalankannya dan di mana
tombolnya duduk**:

* **Form action** (`save`, `save_and_close`, `delete`, `export`,
  `import`) — dijalankan halaman itu sendiri lewat jalur CRUD bawaan.
  Template hasil generate sudah punya tombolnya sejak dulu; schema
  hanya menyatakan tampil atau tidak.

* **Record action** — menembak endpoint `@action` milik viewset untuk
  satu baris (`submit`, `approve`, `reject`, `generate-periods`, …).
  Penandanya adalah kunci ``endpoint``. Tombolnya di dalam
  dialog/workspace baris yang sedang dibuka.

* **Collection action** (`collection()`) — satu endpoint
  `@action(detail=False)` untuk **banyak baris sekaligus** (Post All).
  Penandanya ``scope="collection"``, dan tombolnya di **toolbar
  tabel**: hanya di sana yang tahu penyaring aktif dan baris mana yang
  dicentang.

Bentuk record action **bukan hal baru**: `LEAVE_ACTIONS` dan
`SITE_ROTATION_ACTIONS` sudah lama menulisnya lengkap dengan
`endpoint` / `method` / `refresh` / `confirm` / `fields` /
`visible_when`. Yang hilang adalah sisi frontend — generator tidak
pernah membaca kunci `actions` sama sekali, jadi tombolnya tidak muncul
walau endpoint-nya jalan. Helper di bawah cuma memberi nama pada bentuk
yang sudah dipakai itu supaya tidak perlu ditulis ulang per modul.

Kontraknya:

``key``            pengenal, dipakai sebagai id tombol
``label``          teks tombol
``icon``           nama ikon lucide
``variant``        default / outline / destructive / ghost
``placement``      primary (tombol utama) atau secondary (menu "...")
``modes``          mode halaman tempat tombol boleh tampil
``endpoint``       URL dengan placeholder ``{id}``
``method``         post (bawaan) / put / patch / delete
``payload``        body tetap yang selalu ikut dikirim
``fields``         isian yang diminta lebih dulu, dikirim sebagai body
``form``           form penuh resource lain (lihat ``create_resource``)
``confirm``        True, atau dict {title, description}
``refresh``        muat ulang record setelah berhasil
``visible_when``   syarat tampil, dinilai terhadap record
``permission``     nama wewenang; kosong = tidak dijaga di layar

Tambahan khusus collection action:

``scope``          selalu ``"collection"`` — penanda eksplisit
``selection``      optional / required / none (lihat ``collection()``)
``ids_field``      nama kunci body pembawa id, bawaan ``"ids"``
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def custom(key: str, **kwargs: Any) -> dict[str, Any]:
    return {"key": key, **kwargs}


# ---------------------------------------------------------------------
# Form action
# ---------------------------------------------------------------------

def save(**kwargs: Any) -> dict[str, Any]:
    return custom("save", label="Save", icon="Save", variant="default",
                  placement="primary", modes=["create", "edit"], **kwargs)

def save_and_new(**kwargs: Any) -> dict[str, Any]:
    return custom("save_and_new", label="Save & New", icon="CopyPlus",
                  variant="outline", modes=["create", "edit"], **kwargs)

def save_and_close(**kwargs: Any) -> dict[str, Any]:
    return custom("save_and_close", label="Save & Close", icon="Save",
                  variant="outline", close=True, modes=["create", "edit"], **kwargs)

def cancel(**kwargs: Any) -> dict[str, Any]:
    return custom("cancel", label="Cancel", icon="X", variant="ghost", **kwargs)

def delete(**kwargs: Any) -> dict[str, Any]:
    return custom("delete", label="Delete", icon="Trash2", variant="destructive",
                  method="DELETE", confirm=True, modes=["edit", "detail"], **kwargs)

def export(**kwargs: Any) -> dict[str, Any]:
    return custom("export", label="Export", icon="Download",
                  variant="outline", **kwargs)

def import_data(**kwargs: Any) -> dict[str, Any]:
    return custom("import", label="Import", icon="Upload",
                  variant="outline", **kwargs)


# ---------------------------------------------------------------------
# Record action
# ---------------------------------------------------------------------

def record(
    key: str,
    *,
    endpoint: str,
    label: str,
    icon: str | None = None,
    variant: str = "outline",
    placement: str = "secondary",
    modes: Sequence[str] | None = None,
    method: str = "post",
    payload: Mapping[str, Any] | None = None,
    fields: Sequence[Mapping[str, Any]] | None = None,
    confirm: bool | Mapping[str, Any] | None = None,
    refresh: bool = True,
    visible_when: Mapping[str, Any] | None = None,
    permission: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Tombol yang menembak endpoint `@action` milik viewset.

    `endpoint` memakai placeholder `{id}` — dirakit frontend dari record
    yang sedang dibuka. Sengaja URL penuh, bukan diturunkan dari nama
    action: rute `@action` boleh berbeda dari nama methodnya
    (`url_path="return"` untuk method `send_back`), dan menebaknya
    membuat tombolnya mendarat di 404 tanpa ada yang tahu.
    """
    return custom(
        key,
        label=label,
        icon=icon,
        variant=variant,
        placement=placement,
        modes=list(modes) if modes else ["edit"],
        endpoint=endpoint,
        method=method,
        payload=dict(payload) if payload else None,
        fields=[dict(item) for item in fields] if fields else None,
        confirm=confirm,
        refresh=refresh,
        visible_when=dict(visible_when) if visible_when else None,
        permission=permission,
        **kwargs,
    )


def create_resource(
    key: str,
    *,
    endpoint: str,
    fields: Mapping[str, Any],
    label: str,
    parent_field: str | None = None,
    title: str | None = None,
    columns: int = 2,
    width: str = "xl",
    icon: str | None = None,
    variant: str = "outline",
    placement: str = "primary",
    modes: Sequence[str] | None = None,
    confirm: bool | Mapping[str, Any] | None = None,
    refresh: bool = True,
    visible_when: Mapping[str, Any] | None = None,
    permission: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Tombol yang membuat **dokumen lain** untuk record yang sedang dibuka.

    Bedanya dengan `record()`: yang ditembak bukan endpoint `@action`
    milik record itu, melainkan endpoint koleksi resource lain, dan
    isiannya bukan dua-tiga kolom melainkan form penuh milik resource
    tujuan. `parent_field` diisi id record yang sedang dibuka lalu
    dibuang dari form — dari kartu pegawai, pegawainya tidak boleh bisa
    dipilih ulang; yang membuka kartu Budi tidak boleh tanpa sadar
    membuat dokumen untuk Ani.

    `fields` adalah dict schema resource tujuan apa adanya, jadi
    `visible_when`, lookup, dan kolom pembanding read-only-nya ikut
    tanpa ditulis ulang — dinilai `MFormBuilder` yang sama dengan yang
    dipakai halaman resource itu sendiri. Satu deklarasi, dua pintu
    masuk.
    """
    return custom(
        key,
        label=label,
        icon=icon,
        variant=variant,
        placement=placement,
        # Belum ada recordnya berarti belum ada induk yang bisa
        # ditunjuk — tombolnya tidak masuk akal di layar create.
        modes=list(modes) if modes else ["edit", "detail"],
        endpoint=endpoint,
        method="post",
        form={
            "fields": dict(fields),
            "parent_field": parent_field,
            "title": title or label,
            "columns": columns,
            "width": width,
        },
        confirm=confirm,
        refresh=refresh,
        visible_when=dict(visible_when) if visible_when else None,
        permission=permission,
        **kwargs,
    )


def submit(*, endpoint: str, **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("label", "Submit")
    kwargs.setdefault("icon", "Send")
    kwargs.setdefault("variant", "default")
    kwargs.setdefault("placement", "primary")

    return record("submit", endpoint=endpoint, **kwargs)


def approve(*, endpoint: str, **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("label", "Approve")
    kwargs.setdefault("icon", "CheckCircle2")
    kwargs.setdefault("variant", "default")
    kwargs.setdefault("placement", "primary")
    kwargs.setdefault("confirm", True)

    return record("approve", endpoint=endpoint, **kwargs)


def reject(*, endpoint: str, **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("label", "Reject")
    kwargs.setdefault("icon", "XCircle")
    kwargs.setdefault("variant", "destructive")
    # Penolakan tanpa alasan tidak bisa ditindaklanjuti pengaju — ia
    # hanya tahu ditolak, tidak tahu apa yang harus dibetulkan. Backend
    # sudah menolaknya; isian ini supaya penolakan itu terjadi sebelum
    # request dikirim, bukan sebagai error setelahnya.
    kwargs.setdefault(
        "fields",
        [
            {
                "key": "notes",
                "type": "textarea",
                "label": "Alasan Penolakan",
                "required": True,
            },
        ],
    )

    return record("reject", endpoint=endpoint, **kwargs)


def withdraw(*, endpoint: str, **kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("label", "Withdraw")
    kwargs.setdefault("icon", "RotateCcw")
    kwargs.setdefault("variant", "outline")
    kwargs.setdefault("confirm", True)

    return record("withdraw", endpoint=endpoint, **kwargs)


def copy_to_companies(*, endpoint: str, **kwargs: Any) -> dict[str, Any]:
    """
    Tombol "salin baris ini ke perusahaan lain".

    `endpoint` adalah URL koleksi resource-nya (mis.
    `/api/administration/references/hr/attendance-policies/`); dua rute
    turunannya dirakit di sini supaya tidak ada yang salah ketik satu
    dan menyisakan tombol yang mendarat di 404.

    Pasangannya `CompanyCopyMixin` + `CompanyCopyViewSetMixin` di sisi
    backend. Tanpa keduanya, tombolnya tampil lalu dibalas 404.
    """
    base = endpoint.rstrip("/")

    # Keterangan tambahan milik master ini sendiri — apa yang **tidak**
    # ikut tersalin. Ditempel ke help text field-nya, bukan jadi kunci
    # tersendiri di action: kunci yang tidak dikenal komponennya hilang
    # tanpa suara, dan keterangan yang tidak pernah terbaca sama saja
    # dengan tidak ditulis.
    note = kwargs.pop("help_text", "")

    kwargs.setdefault("label", "Copy to Companies")
    kwargs.setdefault("icon", "Copy")
    kwargs.setdefault("variant", "outline")
    kwargs.setdefault("placement", "secondary")
    kwargs.setdefault("modes", ["edit"])
    kwargs.setdefault("refresh", True)

    kwargs.setdefault(
        "fields",
        [
            {
                "key": "company_ids",
                "type": "multilookup",
                "label": "Target Companies",
                "required": True,
                "endpoint": f"{base}/{{id}}/copy-targets/",
                "label_key": "label",
                "value_key": "value",
                "disabled_key": "already_copied",
                "placeholder": "Pilih company tujuan…",
                "help_text": (
                    "Lokasinya dicocokkan lewat Location Type, bukan "
                    "kodenya — kode hanya unik per company. Yang tidak "
                    "punya lokasi bertipe sama, atau justru punya lebih "
                    "dari satu, dimatikan beserta alasannya."
                    + (f" {note}" if note else "")
                ),
            },
        ],
    )

    return custom(
        "copy_to_companies",
        endpoint=f"{base}/{{id}}/copy-to-companies/",
        method="post",
        **kwargs,
    )


# ---------------------------------------------------------------------
# Collection action
# ---------------------------------------------------------------------

def collection(
    key: str,
    *,
    endpoint: str,
    label: str,
    icon: str | None = None,
    variant: str = "default",
    selection: str = "optional",
    ids_field: str = "ids",
    method: str = "post",
    payload: Mapping[str, Any] | None = None,
    confirm: bool | Mapping[str, Any] | None = None,
    permission: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    Tombol yang menembak endpoint `@action(detail=False)` — berlaku untuk
    **banyak baris sekaligus**, bukan untuk satu record.

    Kenapa ini jenis ketiga dan bukan `record()` tanpa `{id}`: tempat
    tombolnya berbeda. Record action dirender di dalam dialog/workspace
    sebuah baris yang sedang dibuka; yang ini di **toolbar tabel**,
    tempat satu-satunya yang punya akses ke penyaring aktif dan ke baris
    yang dicentang. Modul yang menulis aksi massal sebagai record action
    mendapat tombol yang cuma muncul setelah orangnya membuka satu baris
    — persis pekerjaan yang mau dihindari fitur massal.

    ``selection`` menentukan hubungannya dengan baris yang dicentang:

    ``optional``  ada yang dicentang → kirim id-nya; tidak ada →
                  kirim tanpa id, dan **backend yang menentukan
                  cakupannya lewat `filter_queryset`**. Ini yang dipakai
                  Post All: batch migrasi berisi ratusan baris di tabel
                  berhalaman, dan mencentang semuanya bukan pekerjaan
                  yang bisa diselesaikan siapa pun
    ``required``  harus ada yang dicentang; tombolnya mati kalau tidak
    ``none``      tidak pernah mengirim id sama sekali

    ``scope`` ditulis **eksplisit**, bukan disimpulkan dari tidak adanya
    `{id}` di endpoint. Penanda yang berupa "tidak adanya sesuatu" gagal
    diam-diam ke arah yang salah: satu salah ketik dan aksi massal
    dirender sebagai tombol per baris yang menembak URL tanpa id, lalu
    dibalas 404 tanpa ada yang tahu tombolnya sedang salah tempat.
    """
    if "{id}" in endpoint:
        raise ValueError(
            f"action.collection('{key}') tidak boleh memakai placeholder "
            f"{{id}} — itu record action. Endpoint: {endpoint}"
        )

    allowed = {"optional", "required", "none"}

    if selection not in allowed:
        raise ValueError(
            f"action.collection('{key}'): selection harus salah satu "
            f"dari {sorted(allowed)}, bukan {selection!r}."
        )

    return custom(
        key,
        scope="collection",
        label=label,
        icon=icon,
        variant=variant,
        endpoint=endpoint,
        method=method,
        selection=selection,
        ids_field=ids_field,
        payload=dict(payload) if payload else None,
        confirm=confirm,
        permission=permission,
        **kwargs,
    )
