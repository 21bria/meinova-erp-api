# Contributing

Panduan singkat sebelum menyentuh kode. Anggap ini kata pengantar untuk halaman-halaman lain di seksi ini.

---

## Baca dulu, tiga halaman

1. **[Onboarding](Onboarding.md)** — pasang, migrate, seed, jalankan
2. **[Pipeline BE → FE](../02-Framework/BE-to-FE-Pipeline.md)** — kenapa mengubah model saja tidak mengubah apa pun di layar
3. **[Coding Standards](Coding-Standards.md)** — konvensi yang sudah berlaku

Kalau tugasmu menyentuh dokumen berapproval, tambahkan [Alur Persetujuan Dokumen](../09-business-flows/Document-Approval.md).

---

## Lima prinsip yang membentuk repo ini

Bukan slogan — kelimanya bisa ditunjuk ke kode, dan melanggarnya biasanya menghasilkan bug yang gagal tanpa suara.

### 1. Backend adalah sumber kebenaran untuk UI

Form dan tabel tidak ditulis tangan. Konsekuensinya: **setiap perubahan schema butuh regenerate**, dan lupa melakukannya tidak menghasilkan error apa pun.

### 2. Logika bisnis di service, selalu

Tidak di serializer, tidak di view. Dan `service_class` sendirian **tidak cukup** — `ServiceWriteMixin` harus dipasang.

### 3. Kosong berarti "berlaku untuk semua", bukan "tidak berlaku"

Berlaku di `WorkflowDefinition`, `LeavePolicy`, `RosterPolicy`, `RoleMenuPermission`, `RoleDataPermission`.

**Role tanpa satu pun baris cakupan = tanpa batasan**, bukan tanpa akses. Ini sumber kebocoran data yang paling mudah dibuat tanpa sadar.

### 4. Gagal berisik lebih baik daripada gagal diam

Widget tanpa resolver melempar `NotImplementedError`. Approver yang tidak ketemu menggagalkan seluruh pengajuan. Keduanya disengaja.

Kebalikannya juga: hal yang **tidak boleh** memblokir tetap dicatat sebagai peringatan — nama tidak cocok saat sync absensi, celah antar periode roster.

### 5. Data yang belum ada modelnya tidak diisi angka contoh

Widget "Monthly Payroll" dihapus, bukan diisi nol, karena belum ada model payroll run. Angka karangan di layar demo adalah utang yang dibayar pelanggan — dan `SICK-STD` 30 hari membuktikan itu: angka tanpa dasar hukum yang diseed lalu dianggap sudah divalidasi.

---

## Alur kerja

```
1. Baca kode yang sudah ada di modul terdekat — tiru gayanya
2. Branch: feat/<domain>-<ringkasan>
3. Backend dulu, sampai GET /api/framework/schema/<module>/ membalas 200
4. pnpm meinova generate <module> di repo Nuxt
5. Buka halamannya di browser, coba dengan akun non-superuser
6. Lewati Checklist
7. PR — backend di-merge lebih dulu
```

Detail: [Git Workflow](Git-Workflow.md) · [Pull Request](Pull-Request.md) · [Checklist](Checklist.md)

---

## Kalau kamu menemukan bug yang gagal tanpa suara

Ini kategori yang paling berharga di repo ini, dan ada cara memperlakukannya:

1. **Perbaiki di tempat yang menutup seluruh kelasnya**, bukan satu kejadiannya. Kalau bug ada di satu berkas hasil generate, 99 modul lain kemungkinan punya bug yang sama — tempatnya di `framework/`.
2. **Tulis komentar yang menjelaskan apa yang gagal**, bukan apa yang diperbaiki. Sebagian besar komentar panjang di codebase ini lahir begitu.
3. **Catat di `CLAUDE.md`** kalau keputusannya punya konsekuensi ke depan.
4. **Kalau bisa dites tanpa DB, tulis testnya.** `RosterPolicyResolver.travel_days_for()` yang tidak dioper `policy=` ketahuan lewat test, bukan lewat layar — jadwalnya tetap terbit, cuma tanpa satu pun segmen travel.

---

## Menambah modul baru

[Membuat Modul Baru](../02-Framework/Build-A-Module.md) — tutorial 10 langkah dengan contoh kode utuh.

Yang paling sering terlupa di langkah terakhir: **seed menu dan seed izin**. Tanpa keduanya, modulnya jalan tapi (a) menunya tidak bisa dibatasi per role, dan (b) tombol Save-nya 403 setelah form diisi.

---

## Memperbarui dokumentasi

Dokumentasi bagian dari perubahan, bukan pekerjaan terpisah.

| Kamu mengubah | Perbarui |
|---|---|
| keputusan desain, atau menemukan jebakan baru | `CLAUDE.md` |
| modul baru / status modul berubah | [Module Registry](../03-modules/Module-Registry.md) |
| alur bisnis | `docs/09-business-flows/` |
| perilaku framework | `docs/02-Framework/` |
| menambah halaman docs | `mkdocs.yml` nav |

```bash
mkdocs build --strict     # wajib lolos — menangkap link & anchor rusak
```

!!! note "Hubungan `CLAUDE.md` dengan `docs/`"
    `CLAUDE.md` adalah catatan keputusan yang sangat rinci, termasuk bug yang pernah terjadi dan alasan sebuah pendekatan **tidak** dipakai. `docs/` adalah versi terstrukturnya untuk orang baru.

    Kalau keduanya berbeda: **kode yang menang**, lalu `CLAUDE.md`, baru `docs/`.

---

## Yang jangan dilakukan

- **Menyunting `app/modules/**`** di repo Nuxt — tertimpa saat regenerate
- **Meregenerate tiga tabel Security** tanpa memasang ulang role gating, `notify`, dan label hapusnya
- **Menghidupkan `EmployeeMovement`** sebagai riwayat paralel — itu kode mati tanpa migration
- **Mengembalikan baris travel ke roster** — tanggal penerbangan hanya di `TravelRequest`
- **Menghapus endpoint jalur transisi** sebelum memastikan tidak ada klien yang memanggilnya (agent on-premise ada di sisi klien dan tidak ikut ter-deploy)
- **Menambah pola roster baru** tanpa alasan — dropdown Work Schedule pernah berisi enam pola hampir sama dan itu langsung jadi keluhan pengguna
