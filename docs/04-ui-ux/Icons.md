# Icons

**Lucide**, lewat dua jalur yang harus dijembatani.

---

## Dua kosakata

| Tempat | Gaya | Contoh |
|---|---|---|
| Sidebar (`Menu.icon`) | Nuxt UI | `i-lucide-clock-3` |
| Beranda (katalog, widget, KPI) | kunci `appRegistry` | `clock-3` |

Sidebar memakai nilainya **apa adanya**. Beranda memetakannya lewat `app/registry/app.ts`, jadi `menu_catalog._icon()` di backend **membuang awalan `i-lucide-`**.

!!! danger "Kunci tak dikenal jatuh ke kotak polos, tanpa error"
    Menu baru yang ikonnya belum didaftarkan di registry FE gagal **tanpa suara** — kartunya tetap tampil, cuma kosong.

    26 ikon pernah ditambahkan sekaligus untuk menutup seluruh isi `MENU_TREE`.

---

## Registry

```ts
// app/registry/app.ts
import { Clock3, Users, Building2, CalendarCheck, ... } from 'lucide-vue-next'

export const appRegistry: Record<string, any> = {
  'clock-3': Clock3,
  'users': Users,
  ...
}
```

Import eksplisit, bukan dinamis — supaya tree-shaking bekerja dan ikon yang tidak dipakai tidak ikut ke bundle.

`app.config.ts` menyediakan default `<Icon>`:

```ts
icon: { size: '', class: '' }
```

---

## Menambah ikon

1. Pilih nama dari [lucide.dev](https://lucide.dev)
2. Backend: `i-lucide-<nama>` untuk menu, `<nama>` untuk katalog/widget/KPI
3. Frontend: import + daftarkan di `app/registry/app.ts`
4. **Periksa di browser** — kotak polos berarti kuncinya belum terdaftar

Langkah 3 yang paling sering terlupa, dan satu-satunya cara mengetahuinya adalah melihat layarnya.

---

## Ikon bukan satu-satunya pembeda

Ikon yang sama dipakai beberapa modul adalah hal biasa dan tidak masalah — yang membedakan tetap **labelnya**.

Sebaliknya: jangan mengandalkan ikon sendirian untuk menyampaikan status atau tindakan. Tombol ikon tanpa label butuh tooltip.

---

## Ikon di `app/registry/`

| Berkas | Isi |
|---|---|
| `app.ts` | ikon aplikasi/modul/menu |
| `widget.ts` | nama widget → komponen |
| `badge.ts`, `status.ts` | status → varian badge |
| `color.ts` | nama warna |
| `menu.ts`, `permission.ts` | |

Semuanya mengikuti pola yang sama: **backend mengirim nama, frontend memetakannya, nama tak dikenal jatuh ke bawaan tanpa error.**

Konsekuensinya sama juga: **salah ketik gagal tanpa suara di semua registry ini.**
