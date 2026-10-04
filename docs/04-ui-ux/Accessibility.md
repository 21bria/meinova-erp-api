# Accessibility

!!! warning "Belum diaudit"
    Belum ada audit aksesibilitas, tidak ada tooling, dan tidak ada target WCAG yang ditetapkan.

Halaman ini mencatat apa yang **sudah didapat gratis** dari pilihan teknologi, dan apa yang perlu diperiksa — supaya tidak dimulai dari nol nanti.

---

## Yang sudah didapat dari `reka-ui`

shadcn-vue dibangun di atas **reka-ui** (port Radix), yang memang menangani sebagian besar dasar aksesibilitas:

| | Yang ditangani |
|---|---|
| Dialog | focus trap, `Esc` menutup, fokus kembali ke pemicu |
| Select / Combobox | navigasi keyboard, `aria-expanded`, `aria-activedescendant` |
| Tabs | panah kiri/kanan, `role="tablist"` |
| Checkbox / Radio / Switch | `role` + `aria-checked` |
| Tooltip / Popover | `aria-describedby` |

Artinya komponen dasar sudah relatif aman. Yang perlu diperiksa adalah **cara kita memakainya**.

---

## Yang perlu diperiksa

### 1 · Label field

`MFieldLabel` menghasilkan `<label>`, tapi perlu dipastikan `for`-nya benar-benar terkait ke input — terutama di komponen field yang membungkus input di dalam beberapa lapis.

Field yang labelnya sengaja **tidak** dioper (toolbar filter, supaya judulnya tidak tercetak di atas dropdown) tetap butuh `aria-label`.

!!! bug "Tiga dropdown berjejer semuanya berbunyi 'Select'"
    Karena `label` sengaja tidak dioper dan `placeholder` jatuh ke prop yang tidak ada. Itu masalah kejelasan **dan** aksesibilitas sekaligus — pembaca layar juga membaca "Select" tiga kali.

    Sudah diperbaiki: `MCrudFilters` mengoper `"Select <Label>"`.

### 2 · Pesan error terkait ke fieldnya

`MFieldError` merender pesannya, tapi perlu `aria-describedby` + `aria-invalid` supaya pembaca layar menyebutkannya saat fokus masuk ke field itu.

Banner error non-field (`detail`) sebaiknya `role="alert"` — ia muncul setelah tindakan pengguna dan harus diumumkan.

### 3 · Warna bukan satu-satunya pembeda

Badge status mengambil warnanya dari `state`. Selama teksnya ikut tampil, ini sudah aman — **jangan** membuat kolom yang hanya berupa titik berwarna.

Kesehatan Konfigurasi memisahkan `critical` (danger) dari warning lewat warna **dan** teks.

### 4 · Kontras

Belum diukur. Yang perlu diperiksa lebih dulu:

- `text-*-600` di atas gradien `/15` — teks warna di atas latar berwarna adalah kombinasi yang paling mudah gagal
- Teks pudar pada widget yang disembunyikan di mode Customize
- Placeholder

### 5 · Target sentuh di ponsel

Sistem ini dipakai di ponsel oleh pegawai site. Tombol naik/turun untuk menyusun widget, tombol bintang di kartu quick action, dan tombol mata untuk menyembunyikan — semuanya kecil dan berdekatan.

Minimum 44×44px.

### 6 · Tabel

`MTable` perlu `<caption>` atau `aria-label`, dan header kolom yang bisa disortir perlu `aria-sort`.

Tabel yang bergulir horizontal butuh `tabindex="0"` pada wadahnya supaya bisa digulir dengan keyboard.

### 7 · Fokus setelah tindakan

Setelah menghapus baris atau menutup dialog, fokus harus kembali ke tempat yang masuk akal — bukan lompat ke awal halaman.

Kotak masuk workflow **memundurkan halaman sendiri** saat halaman aktif jadi kosong; fokusnya perlu ikut diarahkan.

---

## Yang tidak boleh diandalkan

!!! danger "Menyembunyikan tombol bukan penjagaan, dan bukan aksesibilitas"
    `useCrud` menyembunyikan tombol yang izinnya tidak ada. Itu kenyamanan — API tetap penjaga sebenarnya.

    Dan **jangan** memakai `visibility: hidden`/`display: none` untuk hal yang sebenarnya perlu diumumkan.

---

## Kalau mau mulai

1. `pnpm dlx @axe-core/cli` pada beberapa halaman utama — hasilnya biasanya mengelompok jadi beberapa pola yang bisa diperbaiki di `framework/`
2. Coba satu alur lengkap **hanya dengan keyboard**: login → buka daftar → Add → isi form → Save
3. Periksa kontras token warna
4. Baru tetapkan target (WCAG 2.1 AA lazimnya cukup)

!!! tip "Perbaikannya di `framework/`, bukan di modul"
    Karena seluruh layar CRUD digenerate, satu perbaikan di `MFormBuilder` atau `MTable` **langsung berlaku di seratus modul tanpa regenerate**.

    Itu keuntungan arsitektural yang jarang ada — audit aksesibilitas di sistem ini jauh lebih murah untuk ditindaklanjuti daripada di aplikasi yang layarnya ditulis satu per satu.
