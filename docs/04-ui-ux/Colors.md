# Colors

---

## Backend menyebut nama, bukan kelas Tailwind

```python
APP_CATALOG = [{"code": "hr", "icon": "users", "color": "blue"}]
```

```ts
// app/registry/color.ts
export const colorRegistry: Record<string, any> = {
  blue:    { bg: 'from-blue-500/15 to-cyan-500/5',      text: 'text-blue-600' },
  emerald: { bg: 'from-emerald-500/15 to-green-500/5',  text: 'text-emerald-600' },
  violet:  { bg: 'from-violet-500/15 to-purple-500/5',  text: 'text-violet-600' },
  orange:  { bg: 'from-orange-500/15 to-amber-500/5',   text: 'text-orange-600' },
  amber: ..., sky: ..., cyan: ..., rose: ...
}
```

Dua alasan, dan yang pertama teknis:

1. **Kelas Tailwind harus ada di build FE.** Kelas yang datang sebagai string dari API tidak terdeteksi saat scan dan **dibuang saat purge** — warnanya tidak muncul, tanpa error.
2. Warna adalah keputusan tampilan yang tidak boleh diketik ulang di setiap katalog.

!!! danger "Nama yang tidak dikenal jatuh ke bawaan, tanpa error"
    Salah ketik di backend **gagal tanpa suara** — kartunya tetap tampil, cuma dengan warna bawaan.

---

## Warna harus konsisten lintas bagian beranda

Pintasan menu menurunkan warnanya dari modulnya lewat `APP_CATALOG`:

> Kartu Applications dan pintasan yang menunjuk modul yang sama **tidak boleh berbeda warna** di satu halaman.

---

## Status: warna dari `state`, bukan dari teksnya

Kolom bertipe `status` di `MDashboardList` mengambil warnanya dari kolom **`state`** pada barisnya.

!!! warning "Jangan turunkan warna dari teks status"
    Status yang sama berbunyi **"Siap"** di satu baris dan **"Terisi 2026"** di baris lain. Mencocokkan teks berarti badge yang sama punya dua warna berbeda.

Pemetaannya di `app/registry/status.ts` dan `badge.ts`.

`critical` pada pemeriksaan Kesehatan Konfigurasi memisahkan **danger** ("sistem tidak bisa dipakai") dari **warning** ("sebaiknya diisi") — pembedanya konsekuensi, bukan selera.

---

## Gradien: di kepala saja

Gradien warna hanya dipakai di **kepala** beranda, bukan di seluruh halaman.

> Latar berwarna di belakang angka adalah cara tercepat membuat kartu data tidak terbaca.

Lingkaran aksen dekoratif wajib **`pointer-events-none`** — tanpa itu ia menutupi tombol Customize dan tombolnya tidak bisa ditekan tanpa satu pun petunjuk kenapa.

---

## Dark mode

Tailwind v4 + shadcn-vue: token warna lewat CSS variable, kelas `dark:` untuk penyesuaian.

Nilai `/15` dan `/5` pada gradien registry dipilih supaya cukup lembut di kedua mode tanpa varian terpisah.

---

## Aturan

- [ ] Backend mengirim **nama**, tidak pernah kelas Tailwind
- [ ] Nama baru didaftarkan di `app/registry/color.ts` sebelum dipakai
- [ ] Warna modul konsisten di seluruh bagian beranda
- [ ] Status mengambil warna dari `state`, bukan dari teksnya
- [ ] Warna bukan satu-satunya pembeda — sertakan label atau ikon
