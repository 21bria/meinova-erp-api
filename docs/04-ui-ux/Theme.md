# Theme

Tailwind CSS v4 + shadcn-vue. Token warna lewat CSS variable, jadi light/dark ditangani tanpa varian komponen terpisah.

---

## Berkas

| | Isi |
|---|---|
| `app/assets/css/tailwind.css` | entry + token |
| `app/app.config.ts` | default `<Icon>` + `appSettings` |
| `components.json` | konfigurasi shadcn |
| `app/registry/color.ts` | nama warna → kelas |

---

## `appSettings`

```ts
export default defineAppConfig({
  icon: { size: '', class: '' },
  appSettings: {
    sidebar: {
      collapsible: 'offcanvas',   // 'offcanvas' | 'icon' | 'none'
      side: 'left',               // 'left' | 'right'
      variant: 'inset',           // 'sidebar' | 'floating' | 'inset'
    },
  },
})
```

Ini pengaturan **aplikasi**, bukan preferensi pengguna — belum disimpan per akun.

Yang **sudah** per pengguna: susunan beranda (`UserDashboardLayout`), katalog aplikasi favorit, dan pintasan menu. Ketiganya di database, bukan di app config.

---

## Responsif

Sistem ini dipakai di ponsel oleh pegawai site, jadi beberapa keputusan tampilan lahir dari situ:

| Keputusan | Alasan |
|---|---|
| **Naik/turun, bukan drag** untuk menyusun widget | di ponsel drag bertabrakan dengan gulir halaman dan selalu terasa rusak; tombol bekerja sama di kedua ukuran layar |
| Kartu KPI jadi **carousel** di layar sempit | empat kartu yang menumpuk jadi empat baris membuat bagian bawah beranda praktis tidak pernah terlihat |
| Quick Actions **dua kolom**, bukan carousel | KPI itu angka yang dibaca satu per satu; quick action itu **tombol yang dicari** — tombol yang harus digeser dulu supaya terlihat lebih lambat daripada tombol yang langsung ada di layar |
| Keterangan quick action **disembunyikan** di layar sempit | di kolom selebar setengah ponsel, kalimatnya terpotong jadi tiga kata yang tidak menjelaskan apa pun |
| `fixed_height` **hanya di `lg` ke atas** | kotak bergulir di dalam halaman yang juga bergulir adalah hal paling menjengkelkan di ponsel |
| Tabel lebar → gulir horizontal di dalam wadahnya | halaman tidak boleh ikut bergulir ke samping |

Dua baris pertama menunjukkan polanya: **pola yang sama tidak otomatis benar untuk isi yang berbeda.**

---

## Tinggi kartu

`fixed_height` ditentukan **katalog widget**, bukan kelas CSS di komponennya.

Tanpa itu, tinggi tiap kartu mengikuti isinya sendiri dan tiga kartu berjejer jadi tiga tinggi berbeda — Notifications yang kosong tinggal seperempat tinggi tetangganya, dan **barisnya terbaca seperti ada yang gagal dimuat**.

!!! warning "Dilepas saat widget-nya dilipat"
    Kalau kelasnya tetap menempel, widget terlipat menyisakan selnya yang setinggi 26rem dan bagian di bawahnya tidak ikut naik — melipat ketiganya justru menghasilkan **satu lubang kosong sebesar layar**, persis kebalikan dari yang diinginkan.

!!! note "`DashboardWidgetFrame` wajib `flex h-full flex-col` + `min-h-0 flex-1` pada slotnya"
    Anak sebuah flex punya `min-height: auto` bawaan, jadi tanpa `min-h-0` kartunya **menolak menyusut** dan `overflow-y-auto` di dalamnya tidak pernah menyala — kartunya memanjang sepanjang daftarnya.

---

## Gradien

Hanya di **kepala** beranda. Latar berwarna di belakang angka adalah cara tercepat membuat kartu data tidak terbaca.

Lingkaran aksen dekoratif wajib `pointer-events-none`.

---

## Dark mode

Token CSS variable, jadi sebagian besar komponen mengikuti tanpa penyesuaian. Nilai `/15` dan `/5` pada gradien registry dipilih supaya cukup lembut di kedua mode.

Kalau menambah komponen: pakai token (`bg-background`, `text-foreground`, `border-border`), **bukan** warna literal.

---

## Yang belum ada

- Preferensi tema per pengguna (light/dark/system) — belum disimpan
- Kustomisasi warna per tenant
- Logo per tenant di UI (`PrintSetting.logo` sudah ada, tapi baru dipakai untuk cetak)
