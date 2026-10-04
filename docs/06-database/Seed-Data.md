# Seed Data

Sistem ini **tidak bisa dipakai tanpa seed**. Master referensi, penomoran, kalender, menu, izin, dan definisi alur semuanya lahir dari perintah seed — bukan dari migrasi.

Urutan lengkap untuk tenant baru: [Onboarding](../08-development/Onboarding.md#4-seed-berurutan).

---

## Dua jenis seed, jangan dicampur

| | Seed sistem | Seed data uji |
|---|---|---|
| Contoh | `seed_administration`, `seed_menus`, `seed_security_roles`, `seed_workflows` | `seed_demo_workforce`, `seed_roster_demo`, `reset_demo_data` |
| Produksi | **wajib** | **jangan pernah** |
| Sifat | idempotent, hanya menambah | membuat/menghapus data uji |

---

## Aturan yang berlaku untuk semua seed

### 1 · Aman diulang

`update_or_create`, selalu. Menjalankan seed dua kali tidak boleh menghasilkan baris ganda.

### 2 · Menambah, tidak mencabut

`seed_security_roles` **menambahkan** izin dan tidak pernah mencabutnya — role yang sudah disunting orang tidak dikembalikan ke bawaan.

Alasannya: seed dijalankan tiap rilis. Kalau ia menimpa, setiap deploy membatalkan konfigurasi yang dibuat admin tenant.

### 3 · Cocokkan lewat kunci yang stabil

`seed_menus` mencocokkan lewat **`route`**, bukan judul — judul berubah jauh lebih sering, dan centang yang sudah disimpan tidak boleh hilang gara-gara "Leave" diganti jadi "Cuti".

!!! bug "Kode grup berprefiks `group:`"
    Tanpa itu grup "Masters" dan menu "Masters" menghasilkan kode yang sama, dan `update_or_create` menimpa baris grupnya diam-diam — seed pertama pernah melaporkan "72 baru, 2 diperbarui" di tabel yang **kosong**.

### 4 · Kode yang ditarik lewat `OBSOLETE_CODES`, dan biasanya soft delete

Pola yang berulang: daftar berubah, tapi `update_or_create` **tidak pernah membuang** kode yang hilang dari daftar.

```python
OBSOLETE_CODES = ["ROS-A", "ROS-B", "ROS-C", "ROS-D"]
```

**Soft delete** kalau modelnya dilindungi `PROTECT` — hard delete akan menggagalkan seluruh seed begitu ada satu dokumen lama yang menunjuknya. `WorkSchedule`/`RosterCrew` kena ini.

Kecuali kalau baris terhapus justru **menghalangi** penyimpanan berikutnya (`FavoriteApp`, `UserDashboardLayout` — constraint uniknya tidak dikondisikan ke `is_deleted`), maka hard delete yang benar.

### 5 · Bawaan tidak ditulis ke DB

Pelajaran yang berulang empat kali (`FavoriteApp.DEFAULT_CODES`, susunan widget, pintasan menu, quick actions):

> **Pembeda "belum pernah menyusun" adalah tidak adanya baris.**

Menulis bawaan saat seed berarti (a) pengguna yang dibuat *setelah* seed tidak dapat apa-apa, dan (b) yang dapat baris bawaan **berhenti mengikuti bawaan yang berubah besok**.

`seed_default_layout` dan `seed_favorite_menus` sudah **dihapus** karena ini.

---

## Jangan seed angka karangan

!!! danger "Contoh nyata: `SICK-STD` 30 hari"
    Pernah diseed sebagai jatah cuti sakit, dan angka itu **karangan** — undang-undang tidak mengatur kuota hari sakit per tahun, melainkan skala upah selama sakit berkepanjangan (100/75/50/25%).

    Angka karangan di master **lebih berbahaya daripada tidak ada angka**: orang menganggapnya sudah divalidasi. Sudah ditarik lewat `OBSOLETE_CODES`.

Cuti besar, melahirkan, dan haid juga sengaja belum punya policy — sampai aturan perusahaannya jelas.

Prinsip yang sama dengan widget dashboard: **yang datanya belum ada tidak dibuat, bukan diisi contoh.**

---

## Kesalahan seed yang gagal sangat jauh dari sumbernya

!!! bug "`is_base` vs `is_base_currency`"
    `apps/administration/seeds/currency.py` menulis kunci `is_base`, sementara kolom modelnya `is_base_currency`.

    `seed_reference` **membuang kunci yang bukan field model — tanpa error**. Jadi **tidak ada satu tenant pun yang punya mata uang dasar** sejak seed pertama.

    Gejalanya muncul di tempat yang sama sekali berbeda: import payroll menjatuhkan currency kosong ke `Currency.is_base_currency`, tidak ketemu, dan **baris penempatan gajinya ditolak**.

    Ditemukan oleh pemeriksaan "Kesehatan Konfigurasi" di dashboard Administration, di menit pertama pemeriksaan itu dibuat.

Pelajaran: seed yang membuang kunci tak dikenal tanpa error adalah jaring yang berlubang. Periksa hasilnya, jangan percaya seed yang "berhasil".

---

## Seed yang paling sering terlupa

| Seed | Kalau dilewati |
|---|---|
| `--only=calendar` | `WorkCalendar`/`Holiday` kosong → hari cuti jatuh ke fallback Senin–Jumat, libur nasional ikut memotong saldo |
| `--only=currency` | tidak ada mata uang dasar (lihat di atas) |
| `--only=numbering` | dokumen tersimpan dengan **nomor kosong** — sengaja tidak melempar, tapi TR tanpa nomor tidak bisa dicetak |
| `seed_security_roles` | seluruh sistem **read-only kecuali superuser** |
| `seed_menus` | menu tidak bisa dibatasi per role — semua orang melihat semuanya |

`--only=calendar` sempat **tidak terdaftar di `SEEDERS`** sama sekali, jadi tidak pernah ikut jalan di tenant mana pun.

---

## Data uji

`seed_demo_workforce` adalah **pemilik tunggal** nomor pegawai, jabatan, department, section, akun, role, dan garis pelaporan. Seed skenario lain hanya **mencari** orangnya lalu menjalankan dokumen; yang belum punya akun **dilaporkan kurang**, bukan dibuatkan diam-diam.

!!! bug "Dulu tiga seed sama-sama membentuk orang yang sama"
    Satu pegawai punya dua akun (`demo.hostaff` dan `demo.hostaff@example.test`), dan garis pelaporannya berganti tergantung seed mana yang dijalankan terakhir. Yang tampak di layar: **meja approval diisi orang yang salah, tanpa ada yang salah konfigurasi.**

    Role di-`set`, bukan di-`add` — kalau ditambah saja, orang yang perannya diubah tetap memegang role lamanya dan satu meja jadi punya dua approver.

Detail keputusannya:

- **Nomor pegawai berawalan `HO`/`GBE`**, tidak meniru pola klien (`KW`, `IP`, `KPB`) — data uji harus bisa dibedakan sekilas dan tidak boleh bertabrakan saat file master klien diimpor. Ini juga yang membuat `reset_demo_data` relatif aman.
- **Tanggal masuk berjenjang** supaya keempat cabang aturan jatah cuti terlewati: penuh, prorata, nol, dan nol-tahun-ini.
- **Tiap orang memegang satu meja.** Kalau dua meja jatuh ke orang yang sama, engine menandai yang belakangan `SKIPPED` dan alur berlapisnya tidak pernah teruji.
- **Site dipilih dari jumlah pegawai**, bukan kode yang ditebak — master tenant lazim memuat sebelas "Default Location" kosong.
- **Dokumen yang sudah `APPLIED` tidak dibuat ulang** saat seed diulang; kalau tidak, kontraknya diperpanjang dua kali dan riwayat pegawainya berubah tiap seed dijalankan.

### Urutan membangun ulang

```
reset_demo_data → seed_workflows → seed_demo_workforce → seed_roster_demo
→ seed_site_travel_demo → seed_workflow_demo → generate_leave_balances
→ seed_employee_action_demo → seed_demo_attendance
```

Dua urutan yang **bukan** selera:

- `seed_roster_demo` **sebelum** `seed_site_travel_demo` — ia membangun ulang seluruh periode roster, dan TR yang menunjuk blok off akan menunjuk baris yang tidak ada lagi
- `seed_demo_attendance` **paling akhir** — hari kerja pegawai site diturunkan dari `RotationPeriod` yang berlaku

!!! warning "`reset_demo_data` hard delete"
    Baris bertanda terhapus tetap menempati kunci uniknya dan justru **menggagalkan pembangunan ulang**.

    Ia menyaring pengajuan workflow lewat `subject_employee`/`submitted_by`, bukan hanya `object_id` — dokumen ditunjuk string tanpa integritas referensial, jadi pembersihan yang kurang teliti meninggalkan pengajuan yatim yang **menahan pegawainya lewat FK ber-`PROTECT`**.

---

## Menulis seeder baru

- [ ] `update_or_create` dengan kunci stabil
- [ ] Terdaftar di `SEEDERS` (untuk `seed_administration`)
- [ ] Kunci dict **cocok dengan nama field model** — yang tidak cocok dibuang tanpa error
- [ ] `OBSOLETE_CODES` untuk kode yang ditarik; soft delete kalau `PROTECT`
- [ ] Bawaan **tidak** ditulis ke DB kalau "belum pernah menyusun" perlu bisa dibedakan
- [ ] Tidak ada angka karangan
- [ ] Diuji dengan dijalankan **dua kali**
