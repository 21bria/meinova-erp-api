# Workspace

Bentuk layar untuk **dokumen** — punya kepala, tab, kartu ringkasan, dan tabel sub-resource. Dipakai Employee, Travel Request, Roster Schedule, Employee Action, Workflow Definition.

Dipilih lewat `ui.workspace()` di schema. Tiga bentuk lainnya: `ui.dialog()`, `ui.page()`, `ui.drawer()`/`ui.wizard()`.

---

## Kapan memakai workspace

| Bentuk | Kapan |
|---|---|
| **Dialog** | master sederhana, < 10 field |
| **Page** | form sedang, tidak bertab |
| **Workspace** | dokumen bertab, punya sub-tabel, punya action Submit/Approve |

Editor `dialog` **tidak butuh** rute create/edit. Workspace butuh tiga: `create`, `[id]`, `[id]/edit`.

!!! warning "Membuatkan rute untuk modul dialog justru error"
    `page.vue`-nya tidak menerima prop `mode`.

---

## Bagian-bagiannya

Hasil generate untuk satu modul workspace:

```
components/
├── <Name>Workspace.vue   ← rangka
├── <Name>Header.vue      ← judul, nomor dokumen, status, tombol action
├── <Name>Overview.vue    ← kartu ringkasan (field ber-overview=True)
├── <Name>Tabs.vue        ← tab
├── <Name>Form.vue        ← form per tab
└── <Name>Table.vue       ← tabel daftar
```

---

## Empat jenis tab

```python
tabs.form(key="general", label="General", fields=[...])
tabs.resource(key="periods", label="Travel Purpose",
              endpoint="/api/hr/rotation-periods/",
              foreign_key="rotation", inline=True, fields={...})
tabs.history(key="history", label="History",
             endpoint="/api/hr/employees/{employee_id}/employment-history/")
tabs.custom(...)
```

| Jenis | Render |
|---|---|
| `form` | field biasa |
| `resource` | tabel sub-resource — dialog per baris, atau inline |
| `history` | timeline generik (`MWorkspaceHistory`) |
| `custom` | ⚠️ **hati-hati** |

!!! danger "`tabs.custom` diteruskan ke slot yang tidak diisi `page.vue`"
    Hasilnya kotak **"This workspace section has not been connected yet."** — lebih buruk daripada tidak ada.

    Karena itu tab `approvals` dicabut dari schema instance workflow dan detailnya ditulis tangan. Tab `history` dulu ikut jatuh ke sini; sekarang sudah punya rendernya.

`MWorkspaceHistory` generik — yang membedakan antar modul cuma `endpoint`, dan placeholder di dalamnya (`{employee_id}`, `{id}`) diganti id record apa adanya. Bentuk barisnya: `{date, type_label, document_number, reason, changes[{label, from, to}]}`.

!!! warning "`ui.workspace()` tanpa key `tabs` = layar kosong"
    `workspaceTabs = []` → **"No workspace tabs available."** Bukan error, cuma kosong, jadi terbaca seperti modul yang belum jadi.

    Daftar field per tab sebaiknya **diturunkan dari `tab=`** (mis. `employment_tab_fields()`), bukan didaftar ulang di `tabs.py` — dua daftar yang harus tetap sama cepat atau lambat berbeda, dan field yang hilang dari daftar tab **tidak muncul di form tanpa satu pun pesan**.

---

## Tab yang pernah dibuka tetap terpasang

!!! bug "Baris yang belum disimpan lenyap saat pindah tab"
    `TabsContent` bawaan **melepas** isi tab yang tidak aktif, dan itu membuang state lokal komponennya. Paling terasa di tabel inline: baris yang baru diketik tapi belum ditekan "Save Rows" hilang begitu penggunanya menengok tab sebelah — persis hal yang membuatnya pindah tab.

Penambalnya `keptTabs` di `<Name>Tabs.vue`: tab yang **pernah** aktif diberi `force-mount` + `data-[state=inactive]:hidden`.

!!! note "`force-mount` sendirian tidak cukup"
    reka-ui memasang `hidden` dari `!present`, dan begitu `force-mount` menyala `present` selalu true — sehingga tab yang tidak aktif justru **ikut tampil**. Kelas CSS itu yang menyembunyikannya.

Sengaja hanya tab yang **pernah dibuka**, bukan semuanya: tiap tab resource menembak satu request daftar saat dipasang.

---

## Tabel resource inline

`inline=True` memilih `MWorkspaceResourceInline` — baris disunting langsung di grid.

Dipakai untuk jadwal: menambah lima baris tanggal lewat lima modal membuat baris yang justru harus dibandingkan **tidak pernah terlihat bersamaan**. Dialog tetap jadi bawaan untuk tab resource lain.

Aturan yang menyertainya:

| Aturan | Kenapa |
|---|---|
| Kolom = field `table=True` | satu-satunya kenop pengatur lebar tabel |
| Dua tabel dari endpoint sama **wajib bawa salinan config field sendiri** | grid memilih kolom dari flag `table`; mengubahnya di tempat ikut mengubah tabel yang satunya |
| `foreign_key` yang menembus relasi **wajib** ada di `filterset_fields` | tanpa itu grid menampilkan data seluruh tenant |
| `create=False` | menyembunyikan Add Row |

Lookup di dalam baris menyaring lewat `$<foreign_key>` — komponen inline menanam id dokumen di setiap baris (draft maupun tersimpan). Kunci itu ikut terkirim ke API dan diabaikan DRF karena bukan field serializer.

### Kolom turunan: `compute`

```python
compute={"kind": "date_diff", "from": "start_date", "to": "end_date", "inclusive": True}
```

**Wajib ada** kalau service menghormati nilai kiriman sebagai isian manual: baris di grid selalu membawa nilai lamanya, jadi tanpa perhitungan ulang di klien, **mengubah tanggal menyimpan jumlah hari yang lama tanpa pesan apa pun**.

Dideklarasikan di schema, bukan ditanam di komponen — tabel inline dipakai resource mana pun.

`total_days` inklusif; `accommodation_nights` tidak, karena malam bukan hari.

---

## Contoh nyata: tiga tabel inline di satu dokumen

Travel Request punya `Travel Purpose` (`RotationPeriod`) plus `Travel Arrangement` dan `Accommodation` — **dua tabel terakhir membaca endpoint yang sama** dengan kolom berbeda.

Akomodasi dipisah karena satu tabel 18 kolom memaksa orang menggulir ke samping hanya untuk melihat kolom yang sedang diisinya — dan di formulir TR aslinya akomodasi memang tabel tersendiri.

Tabel Accommodation memakai `create=False`: barisnya dibuat di Travel Arrangement, dan baris akomodasi tanpa tanggal berangkat akan ditolak server.

---

## Field read-only di workspace

Generator membuang field ber-`read_only` dari `form.ts`. Field turunan yang sengaja ditaruh di sebuah tab **hilang tanpa error** — schema-nya benar, tab-nya menyebutnya, layarnya kosong.

**Perbaikannya `display=True`.** Jangan `form=True`.

Kepala Travel Request memakai ini: `department_name`, `section_name`, `position_name`, `join_date`, `point_of_hire_name` semuanya read-only turunan dari relasi. **Dibaca dari relasi, tidak disalin** — menyalinnya ke dokumen berarti dua versi data yang sama dan yang satu diam-diam basi.

Konsekuensinya: relasi itu **wajib** ikut `select_related` di viewset.

---

## Error di workspace

Pernah gagal total: tombol Save ditekan, tidak terjadi apa-apa. Dua sebab khusus workspace:

1. `<X>Form.vue` menyaring error ke kunci yang cocok dengan kolom tab itu (`tabErrors`) — `detail` dibuang sebelum sempat dirender
2. `page.vue` menangkap kegagalan simpan dan menelannya diam-diam — benar untuk 400 per-field, **salah untuk 403**

Keduanya di **berkas hasil generate**, dan sudah diperbaiki di template + di `normalizeApiErrors`. Modul lama dapat toast-nya tanpa diregenerate; banner-nya menyusul setelah regenerate.

---

## Checklist

- [ ] `ui.workspace()` punya key `tabs`
- [ ] Rute `create`, `[id]`, `[id]/edit` ada di `app/pages/<framework_module>/`
- [ ] Daftar field per tab diturunkan dari `tab=`, bukan didaftar ulang
- [ ] Field read-only yang harus tampil diberi `display=True`
- [ ] Relasi yang dibaca kepala dokumen ikut `select_related`
- [ ] `foreign_key` tab resource ada di `filterset_fields`
- [ ] Kolom turunan di grid inline punya `compute`
- [ ] Tidak ada `tabs.custom` kecuali komponennya memang disiapkan
