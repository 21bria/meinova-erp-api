# Urutan Entry: dari Employee sampai Cuti

Panduan urutan pengisian untuk tenant yang **baru berisi pegawai saja** —
hasil `tenant_command seed_demo --reset --employees-only`. Cuti, saldo,
roster, presensi, dan seluruh dokumen sengaja kosong supaya setiap
langkahnya bisa ditelusuri sendiri.

Dua jalur dijelaskan berdampingan sepanjang dokumen, karena keduanya
memang berbeda dan perbedaannya justru yang paling sering salah dipahami:

| | **Kantor Pusat (HO)** | **Site** |
|---|---|---|
| Pola kerja | Kalender kerja (Senin–Jumat) | Roster blok on/off (POH) atau kalender site (lokal) |
| Perlu Roster Setup? | **Tidak** | **Ya**, untuk pegawai Point of Hire |
| Hari cuti dihitung dari | `WorkCalendar` — akhir pekan & libur nasional dikecualikan | blok roster (POH) / kalender site (lokal) |
| Alur persetujuan cuti | `HR-HO-LEAVE` — 3 meja | `HR-LEAVE-SITE` — 6 meja |
| Travel Request | tidak berlaku | berlaku untuk POH |

---

## 0. Peta urutan

```
        ┌─ MASTER (sudah terisi seed) ─────────────────────────────┐
        │ Organisasi · Kalender · Shift · Leave Policy             │
        │ Roster Policy · Attendance Policy · Workflow Definition  │
        └──────────────────────────────────────────────────────────┘
                                  │
   ①  Employee  ──────────────────┼──────────────────────────────────
      (26 orang sudah ada; tambah sendiri untuk mencoba form-nya)
                                  │
   ②  Jatah cuti  ────────────────┤   HO & Site sama-sama butuh
      Leave Balance               │
                                  │
   ③  Roster Setup  ──────────────┤   SITE (POH) saja
      RosterSetupRequest          │
                                  │
   ④  Presensi  ──────────────────┤   opsional, bisa menyusul
      Attendance                  │
                                  │
   ⑤  Dokumen  ───────────────────┘
      Cuti · Travel Request · Employee Action
```

**Urutannya bukan selera.** Tiap panah di atas adalah dependensi nyata:

- ② sesudah ① — jatah cuti dihitung dari **Join Date**; tanpa pegawai,
  `generate_leave_balances` menulis nol baris tanpa mengeluh.
- ③ sesudah ① — dokumen Roster Setup memilih pegawai dari satu site.
- ⑤ sesudah ② — cuti memotong saldo. Kalau saldonya belum terbit,
  potongannya mendarat di angka minus yang terbaca seperti salah hitung.
- ⑤ sesudah ③ untuk site — hari cuti pegawai roster dihitung dari blok
  on/off yang berlaku. Cuti yang diajukan sebelum rosternya terbit tetap
  tersimpan, tapi jumlah harinya dihitung dari kalender site, bukan dari
  jadwalnya sendiri.

---

## 1. Employee

**Layar:** `HR → Employees` (`/hr/employees`)

Tenant sudah berisi 26 pegawai lengkap seluruh tab (lihat
[Daftar akun peragaan](#daftar-akun-peragaan)). Untuk mencoba form-nya,
tambah pegawai baru dan isi tab berikut berurutan.

### Tab yang wajib, dan apa yang ditentukannya

| Tab | Kolom penentu | Yang bergantung padanya |
|---|---|---|
| **General** | Province → Kabupaten/Kota → Kecamatan → Kelurahan | Alamat berjenjang; dropdown anak terkunci sampai induknya diisi |
| **Organization** | Company · Location · Department · Section · Position | Ke **meja siapa** dokumennya mendarat |
| | **Reports To** | Step "Atasan Langsung" di seluruh alur |
| **Current Employment** | **Join Date** | Jatah cuti (masa tunggu 12 bulan) |
| | Employee Group | Pencocokan Leave Policy / Roster Policy |
| **Contract & Probation** | Employment Type | Muncul-tidaknya kolom kontrak (`requires_contract`) |
| **Work Arrangement** | **Shift** | Seluruh perhitungan keterlambatan |
| | Working Calendar | Hari cuti pegawai non-roster |
| | **Point of Hire** | Hari perjalanan pegawai roster |
| **Bank Accounts** | Bank · No. Rekening | Pembayaran payroll |
| **Payroll** | Payroll Group · Tax Status (PTKP) | Perhitungan pajak |

### Empat kolom yang paling sering salah

1. **Section menentukan meja pertama alur site.** Step #1 `HR-LEAVE-SITE`
   mencari pemegang `ADMIN-SECTION` **di section pegawainya**. Section
   yang kosong atau salah membuat dokumennya melompat ke turunan
   berikutnya — tetap jalan, tapi bukan ke meja yang dimaksud.

2. **Reports To bukan hierarki jabatan.** Yang dibaca engine adalah
   `reports_to` antar-**orang** di tab Organization, bukan `reports_to`
   antar-Position di master. Kosong = step "Atasan Langsung" tidak
   menemukan siapa pun, dan **seluruh pengajuan gagal** (step itu tidak
   punya cadangan).

3. **Shift kosong = keterlambatan tidak pernah dihitung.** Bukan nol
   menit — tidak dihitung sama sekali, dan barisnya terbaca seperti
   pegawai yang selalu tepat waktu.

4. **Point of Hire hanya untuk pegawai yang didatangkan.** Tenaga lokal
   (`LOK…` di data peragaan) sengaja dikosongkan: mereka tidak punya
   tiket pulang, jadi tidak punya hari perjalanan.

### Nomor pegawai

Nyalakan **Auto Generate Employee Number** dan pilih Company — nomor
berikutnya langsung tampil (`MMR260027`). Angka itu **tebakan**; yang
benar-benar terbit dialokasikan saat Simpan.

> Untuk mencoba, matikan Auto dan ketik nomornya sendiri. Awalan
> `HO`/`SGA`/`LOK` dipakai data peragaan — pakai awalan lain supaya
> `reset_demo_data` tidak ikut membuangnya.

---

## 2. Jatah cuti

**Layar:** `HR → Masters → Leave Policy` lalu `HR → Attendance & Leave → Leave Balance`

Ini langkah yang paling sering dilewati, dan gejalanya paling
membingungkan: form cuti bisa dibuka, tanggalnya bisa diisi, lalu
saldonya minus.

### 2.1 Periksa Leave Policy

`/hr/leave-policies` — bawaan tenant hanya **`ANNUAL-STD`** (12 hari
setelah 12 bulan kerja, prorata periode pertama, sesuai UU
Ketenagakerjaan).

> **Jenis cuti tanpa policy tidak menghasilkan baris saldo sama sekali.**
> Cutinya tetap bisa dicatat, cuma tidak ada angka yang dipotong. Itu
> perilaku yang benar untuk cuti tak berkuota (sakit, melahirkan, duka).

Kolom kosong pada Scope berarti **"berlaku untuk semua"**, bukan "tidak
berlaku". Aturan bercompany menang atas yang global.

> Rincian lengkapnya — rumus prorata, urutan kantong, saldo migrasi,
> carry over, dan angka yang akan keluar untuk ke-26 pegawai — ada di
> [Menentukan Saldo Cuti](Leave-Balance-Setup.md).

### 2.2 Terbitkan saldonya

```bash
python manage.py tenant_command generate_leave_balances --year=2026 --schema=demo
python manage.py tenant_command generate_leave_balances --year=2027 --schema=demo
```

Tambahkan `--dry-run` untuk melihat hasilnya lebih dulu, dan
`--verbose-rows` untuk membaca alasan per pegawai.

**Nol selalu punya alasan yang bisa dibaca**, dan data peragaan sengaja
mencakup keempat keadaannya:

| Pegawai | Join Date | Hasil 2026 |
|---|---|---|
| `HO001` Sarah Wibowo | 2019-01-07 | jatah penuh |
| `HO003` Bimo Nugroho | 2025-08-15 | prorata — berhak 15 Ags 2026 |
| `SGA006` Eko Prasetyo | 2026-07-01 | **nol** — belum genap 12 bulan |
| `LOK008` Nurlela Wahab | 2026-04-06 | **nol** tahun ini, prorata 2027 |

> Saldo juga **terbit sendiri** saat Join Date diisi lewat form Employee.
> Perintah di atas tetap dipakai untuk pergantian tahun dan sesudah
> policy diubah.

### 2.3 Kalau tenant migrasi dari sistem lama

Pakai `HR → Attendance & Leave → Leave Opening Balance`
(`/hr/leave-opening-balances`) — satu baris per pegawai per jenis cuti,
bertanggal go-live. **Jangan** mengetik angkanya langsung ke kartu saldo:
kolom `opening_balance` dijumlah ulang dari dokumen ini, jadi isian
manual akan tertimpa tanpa satu pun pesan.

Ada juga import massal: `HR → Leave Opening Balance → Import`.

---

## 3. Roster — SITE saja

**Layar:** `HR → Roster & Travel → Roster Setup` (`/hr/roster-setups`)

Lewati bagian ini untuk pegawai kantor pusat **dan** untuk tenaga lokal
site — keduanya tidak punya blok on/off.

### 3.1 Periksa Roster Policy lebih dulu

`/hr/roster-policies` — dua baris sudah diseed untuk Sagea Mine:

| Kode | Pola | Bawaan |
|---|---|---|
| `ROSTER-SAGEA MINE-6-2` | 42 hari kerja / 14 hari off | ✔ |
| `ROSTER-SAGEA MINE-8-2` | 56 hari kerja / 14 hari off | |

Tab **Travel Days by POH** memuat hari perjalanan per kota asal —
Makassar 2 hari, Yogyakarta/Bandung/Luwuk Banggai 3 hari. Angka inilah
yang membuat dua orang di satu crew punya jendela travel berbeda.

### 3.2 Buat dokumen Roster Setup

1. **Company** → `Meinova Mineral Resources`
   Diisi lebih dulu, bukan kenyamanan: master memuat banyak lokasi
   bernama mirip, dan tanpa Company dropdown Site tidak bisa dibedakan.
2. **Site** → `Sagea Mine`
3. **Department / Section** *(opsional)* — penyaring kandidat.
   Keduanya berdiri sendiri; Section boleh diisi tanpa Department.
4. **As Of Date** dan **Horizon Months** (bawaan 12).
5. Simpan.

### 3.3 Tambahkan pegawainya

Tekan **Add Employees** di kepala dokumen. Daftar kandidat = pegawai
site yang **belum punya rencana berjalan** — 18 orang di tenant
peragaan.

> Tenaga lokal (`LOK…`) ikut muncul di daftar. Itu memang benar — mereka
> layak dipilih kalau perusahaan memutuskan memberinya roster — tapi
> untuk peragaan ini pilih yang berawalan **`SGA`** saja.

Per baris isi:

| Kolom | Isi |
|---|---|
| **Roster Policy** | `ROSTER-SAGEA MINE-6-2` atau `-8-2` |
| **Current Cycle Start** | tanggal mulai siklus orang itu |
| Opening Rotation Credit | biasanya 0 |

**Jangkarnya per orang, bukan per crew.** Di site yang gelombangnya
bergantian, dua orang berpola sama memang punya tanggal mulai berbeda —
itu keadaan normal, bukan kesalahan input. Untuk memperagakannya, beri
beberapa orang tanggal berbeda (mis. 1 Agustus, 15 Agustus, 1 September).

### 3.4 Preview → Submit → Commit

1. **Preview** — hasilnya sama persis dengan yang akan disimpan.
   Temuan dipisah dua: **blocking** (harus dibetulkan) dan **warning**
   (mis. belum punya pasangan back-to-back — tidak pernah memblokir).
2. **Submit** — masuk alur `HR-ROSTER-SETUP`.
   > Satu batch = **satu Site**, dan alurnya hanya boleh memakai step
   > Role/User. "Atasan langsung" dari tiga puluh orang bukan satu orang;
   > kalau alurnya memuat step itu, Submit ditolak dengan menyebut
   > step-nya.
3. **Approve** lewat `Workflow → Inbox` (`/workflow/inbox`).
4. **Commit** — barulah jadwalnya terbit.

Commit dijalankan **per baris di dalam savepoint sendiri**: satu baris
gagal tidak membatalkan sisanya. Yang gagal ditandai `FAILED` beserta
alasannya, dan Commit bisa diulang — baris yang sudah `COMMITTED`
dilewati.

### 3.5 Hasilnya

Buka `HR → Roster & Travel → Roster Schedule` (`/hr/site-rotations`).
Tiap orang punya deret segmen:

```
WORK ──► TRAVEL_OUT ──► FIELD_BREAK ──► TRAVEL_IN ──► WORK ──► …
42 hari     2 hari         14 hari        2 hari
```

Sesudah ini, hari cuti pegawai tersebut dihitung dari blok roster —
bukan lagi dari kalender site.

### 3.6 Menyesuaikan yang sudah berjalan

**Jangan generate ulang.** Pakai `HR → Roster Adjustment`
(`/hr/roster-adjustments`): ia bekerja dari satu titik ke depan dan tidak
menyentuh baris yang sudah dijalani. Delapan jenis, dan yang membedakan
**siapa penyebabnya** — kapal delay bukan hal yang sama dengan pegawai
yang terlambat kembali, walau selisih harinya sama.

---

## 4. Presensi *(opsional)*

**Layar:** `HR → Attendance & Leave → Attendance` (`/hr/attendance`)

Tiga jalur masuk, dan ketiganya menulis ke tabel yang sama:

| Jalur | Kapan dipakai |
|---|---|
| Ketik manual | koreksi satuan |
| **Import** berkas fingerprint | `/hr/attendance/import` |
| Sync agent on-premise | `POST /api/hr/attendance/sync/` |

Toleransi keterlambatan dan ambang lembur diatur di
`HR → Masters → Attendance Policy` (`/hr/attendance-policies`). Bawaannya
`ATT-STD` global **tanpa toleransi** — berapa menit yang boleh dimaafkan
tidak diatur undang-undang mana pun, jadi angkanya sengaja tidak dikarang.

> Mengubah policy **tidak** mengubah baris lama. Jalankan
> `tenant_command recalculate_attendance --start= --until=` untuk itu.
> Kalau otomatis, laporan bulan lalu yang sudah dikirim ke manajemen
> berubah diam-diam setiap kali ada yang menggeser satu angka.

Ketidakhadiran adalah **baris yang tidak ada**, bukan baris berstatus
Absent. `tenant_command close_attendance` yang mengubahnya jadi baris
`absent` — sampai itu dijalankan, Tingkat Kehadiran di dashboard selalu
100%.

---

## 5. Ajukan cuti

**Layar:** `HR → Attendance & Leave → Leave` (`/hr/leave`)

Dua jalur di satu tabel, dan bedanya bukan detail:

| | **Pencatatan** | **Pengajuan** |
|---|---|---|
| Siapa | HR mencatat cuti yang sudah terjadi | pegawai mengajukan sendiri |
| Status | langsung `RECORDED` | `DRAFT → SUBMITTED → APPROVED` |
| Lewat alur | tidak | ya |
| Memotong saldo | ya, seketika | **hanya setelah `APPROVED`** |

Cuti yang masih `SUBMITTED` **belum** memotong apa pun: yang belum
disetujui tidak boleh sudah mengurangi jatah orang.

### 5.1 Jalur HO — 3 meja

Login `demo.hostaff` (HO003 Bimo Nugroho, Finance Staff).

1. Buat cuti → pilih Leave Type **Annual Leave**, tanggal, lalu **Submit**.
2. Dokumennya berjalan lewat `HR-HO-LEAVE`:

| # | Meja | Diisi | Akun |
|---|---|---|---|
| 1 | Approved By (Atasan Langsung) | HO005 Farah Anindita | `demo.homanager` |
| 2 | Acknowledged By (Kepala Departemen) | HO005 (sama → **dilewati**, tercatat "sudah terwakili") | — |
| 3 | Approved By (HR Manager) | HO001 Sarah Wibowo | `demo.hrmanager` |

> **Meja #3 hanya jalan untuk cuti ≥ 5 hari.** Aturannya ada di
> `WorkflowStep.condition`, bukan ditanam di kode modul cuti — jadi cuti
> dua hari yang sudah disetujui atasan langsung tidak menunggu meja
> ketiga.

**Contoh angka yang bisa dicocokkan:** cuti 14–18 Agustus 2026 =
5 hari kalender, tapi hanya memotong **2 hari** saldo. Sabtu dan Minggu
bukan hari kerja, dan 17 Agustus libur nasional.

### 5.2 Jalur Site — 6 meja

Login `demo.sitestaff` (SGA002 Ahmad Sudrajat, Grade Control Foreman).

| # | Meja | Cakupan | Diisi | Akun |
|---|---|---|---|---|
| 1 | Prepared By (Admin Section) | Section | SGA003 Bayu Prakoso | `demo.siteadmin` |
| 2 | Reviewed By (Admin HR Site) | Location | SGA006 Eko Prasetyo | `demo.sitehradmin` |
| 3 | Approved By (Atasan Langsung) | — | SGA001 Rinaldo Saputra | `demo.sitespv` |
| 4 | Approved By (HR Manager Site) | Location | SGA004 Citra Halimah | `demo.sitehrmanager` |
| 5 | Approved By (KTT Site) | Location | SGA005 Dedi Kurniawan | `demo.ktt` |
| 6 | Issued By (HRGA) | Company | HO004 Clara Wijaya | `demo.hrga` |

Lima meja pertama ada di site — dokumennya baru menyeberang ke Jakarta
di meja terakhir, tepat saat tiketnya benar-benar dibeli.

**Turunan meja #1 sengaja bertingkat**, dan ketiganya bisa dicoba
langsung di tenant peragaan:

| Pengaju | Section | Meja #1 jatuh ke | Kenapa |
|---|---|---|---|
| `SGA002` | Site Operations | SGA003 (`ADMIN-SECTION`) | ada adminnya sendiri |
| `LOK002` | Hauling | LOK001 (`ADMIN-DEPARTMENT`) | section tanpa admin → naik ke department |
| `SGA009` | HSE / General | SGA006 (`HR-ADMIN`) | department pun tidak punya → melebar ke HR site |

Alasan pengalihannya tercetak di kotak tanda tangannya, lengkap dengan
tingkat mana saja yang sudah dicoba.

### 5.3 Menyetujui

Semua keputusan lewat **satu kotak masuk**: `Workflow → Inbox`
(`/workflow/inbox`). Approver tidak perlu membuka layar Cuti untuk
menyetujui cuti dan layar TR untuk menyetujui TR.

Tiga tombol, dan yang ketiga sering terlupa:

- **Approve** — lanjut ke meja berikutnya
- **Reject** — dokumen selesai, ditolak
- **Return** — dikembalikan ke pengaju **untuk diperbaiki**. Tanpa ini,
  satu tanggal salah ketik hanya punya dua pilihan: ditolak, atau
  disetujui dengan isi yang salah.

---

## 6. Travel Request — site (POH) saja

**Layar:** `HR → Roster & Travel → Travel Request`

Jangan tertukar dengan Roster Schedule:

| | Roster Schedule | Travel Request |
|---|---|---|
| Isinya | jadwal kerja setahun | **satu kepulangan** |
| Jumlah per orang | satu | banyak |
| Yang dibelikan tiket | — | ✔ |

**Roster bukan syarat TR.** Pegawai site yang jadwalnya belum disusun
tetap bisa mengajukan; kalau blok off-nya dipilih, tanggalnya disalin
dari sana sebagai **usulan**, bukan pengunci.

Satu pengajuan boleh membawa beberapa alasan — 7 hari Field Break lalu
7 hari Cuti Tahunan. Yang membedakan `RotationPurpose.deducts_leave`:
Field Break tidak memotong saldo, Cuti Tahunan memotong.

**Catatan cutinya terbit saat dokumen disetujui**, bukan saat diketik.

---

## Daftar akun peragaan

Password seluruh akun: **`<DEMO_PASSWORD>`** (nilai variabel lingkungan `DEMO_PASSWORD` saat `seed_demo`). Superadmin: `admin`.

### Kantor Pusat Jakarta — 8 orang

| No | Nama | Jabatan | Akun | Role |
|---|---|---|---|---|
| `HO006` | Adrian Mahendra | General Manager | `demo.gm` | EMPLOYEE |
| `HO001` | Sarah Wibowo | HR Manager | `demo.hrmanager` | HR-MANAGER, WORKFLOW-ADMIN |
| `HO002` | Hesti Rahayu | HR Officer | `demo.hradmin` | HR-ADMIN |
| `HO004` | Clara Wijaya | HRGA Officer | `demo.hrga` | HRGA |
| `HO005` | Farah Anindita | Finance Manager | `demo.homanager` | EMPLOYEE |
| `HO003` | Bimo Nugroho | Finance Staff | `demo.hostaff` | EMPLOYEE |
| `HO007` | Rangga Pratomo | Accounting Staff | `demo.accstaff` | EMPLOYEE |
| `HO008` | Yulia Kartika | GA Staff | `demo.gastaff` | EMPLOYEE |

### Site Sagea — Point of Hire (10 orang, kandidat roster)

| No | Nama | Jabatan | POH | Akun | Role |
|---|---|---|---|---|---|
| `SGA001` | Rinaldo Saputra | Project Manager | Makassar | `demo.sitespv` | EMPLOYEE |
| `SGA004` | Citra Halimah | Site HR Manager | Yogyakarta | `demo.sitehrmanager` | HR-MANAGER |
| `SGA005` | Dedi Kurniawan | Kepala Teknik Tambang | Makassar | `demo.ktt` | KTT |
| `SGA006` | Eko Prasetyo | Site HR Officer | Bandung | `demo.sitehradmin` | HR-ADMIN |
| `SGA003` | Bayu Prakoso | Section Admin | Bandung | `demo.siteadmin` | ADMIN-SECTION |
| `SGA002` | Ahmad Sudrajat | Grade Control Foreman | Luwuk Banggai | `demo.sitestaff` | EMPLOYEE |
| `SGA010` | Yusuf Maulana | Hauling Foreman | Makassar | `demo.haulingspv` | EMPLOYEE |
| `SGA007` | Ferry Wibisono | Plant Supervisor | Sorong | `demo.plantspv` | EMPLOYEE |
| `SGA008` | Gilang Ramadhan | Surveyor | Yogyakarta | `demo.surveyor` | EMPLOYEE |
| `SGA009` | Novita Sari | HSE Officer | Makassar | `demo.hse` | EMPLOYEE |

### Site Sagea — tenaga lokal (8 orang, tanpa roster)

| No | Nama | Jabatan | Section | Akun | Role |
|---|---|---|---|---|---|
| `LOK001` | Rustam Hasan | Department Admin | OPS General | `demo.deptadmin` | ADMIN-DEPARTMENT |
| `LOK002` | Jufri Sangaji | Heavy Equipment Operator | Hauling | `demo.opr1` | EMPLOYEE |
| `LOK003` | Rahmat Tidore | Heavy Equipment Operator | Hauling | `demo.opr2` | EMPLOYEE |
| `LOK004` | Sultan Ahmad | Heavy Equipment Operator | Hauling | `demo.opr3` | EMPLOYEE |
| `LOK005` | Umar Sahdan | Mechanic | Mechanical | `demo.mech1` | EMPLOYEE |
| `LOK006` | Taufik Ode | Electrician | Electrical | `demo.elec1` | EMPLOYEE |
| `LOK007` | Hamid Latif | Logistic Staff | LOG General | `demo.log1` | EMPLOYEE |
| `LOK008` | Nurlela Wahab | Surveyor | Survey | `demo.survey2` | EMPLOYEE |

### Rantai komando

Yang dibaca engine approval adalah **`Reports To` antar-orang** di tab
Organization, bukan hierarki jabatan di master Position dan bukan Job
Level. Pohon di bawah ini persis isi kolom itu di tenant peragaan; Job
Level ikut dicetak supaya terlihat bahwa jenjangnya memang menurun ke
bawah.

Jenjang Job Level di master tenant ini:
`STAFF (10) → SUP Supervisor (20) → SPV Superintendent (30) → MGR Manager (40) → GM (50) → DIR (60)`.

```
HO006  Adrian Mahendra    — General Manager            [GM   ] [HO]
├── HO001  Sarah Wibowo       — HR Manager                 [MGR  ] [HO]
│   ├── HO002  Hesti Rahayu       — HR Officer                 [STAFF] [HO]
│   ├── HO004  Clara Wijaya       — HRGA Officer               [STAFF] [HO]
│   └── HO008  Yulia Kartika      — GA Staff                   [STAFF] [HO]
├── HO005  Farah Anindita     — Finance Manager            [MGR  ] [HO]
│   ├── HO003  Bimo Nugroho       — Finance Staff              [STAFF] [HO]
│   └── HO007  Rangga Pratomo     — Accounting Staff           [STAFF] [HO]
└── SGA001 Rinaldo Saputra    — Project Manager            [GM   ] [POH Makassar]
    ├── LOK001 Rustam Hasan       — Department Admin           [STAFF] [lokal]
    ├── LOK007 Hamid Latif        — Logistic Staff             [STAFF] [lokal]
    ├── SGA002 Ahmad Sudrajat     — Grade Control Foreman      [SUP  ] [POH Luwuk Banggai]
    ├── SGA003 Bayu Prakoso       — Section Admin              [STAFF] [POH Bandung]
    ├── SGA004 Citra Halimah      — Site HR Manager            [MGR  ] [POH Yogyakarta]
    │   └── SGA006 Eko Prasetyo       — Site HR Officer            [STAFF] [POH Bandung]
    ├── SGA005 Dedi Kurniawan     — Kepala Teknik Tambang      [MGR  ] [POH Makassar]
    ├── SGA007 Ferry Wibisono     — Plant Supervisor           [SUP  ] [POH Sorong]
    │   ├── LOK005 Umar Sahdan        — Mechanic                   [STAFF] [lokal]
    │   └── LOK006 Taufik Ode         — Electrician                [STAFF] [lokal]
    ├── SGA008 Gilang Ramadhan    — Surveyor                   [STAFF] [POH Yogyakarta]
    │   └── LOK008 Nurlela Wahab      — Surveyor                   [STAFF] [lokal]
    ├── SGA009 Novita Sari        — HSE Officer                [STAFF] [POH Makassar]
    └── SGA010 Yusuf Maulana      — Hauling Foreman            [SUP  ] [POH Makassar]
        ├── LOK002 Jufri Sangaji      — Heavy Equipment Operator   [STAFF] [lokal]
        ├── LOK003 Rahmat Tidore      — Heavy Equipment Operator   [STAFF] [lokal]
        └── LOK004 Sultan Ahmad       — Heavy Equipment Operator   [STAFF] [lokal]
```

Dua rantai **crew → supervisor → manager** yang bisa diuji:
Hauling (`LOK002/003/004 → SGA010 → SGA001`) dan
Plant (`LOK005/006 → SGA007 → SGA001`).

**Sepuluh orang melapor langsung ke `SGA001`**, dan itu memang bentuk
site yang kepalanya satu. Yang perlu diperhatikan saat memakainya:

- **`SGA005` (KTT) melapor ke Project Manager, bukan sebaliknya.** KTT
  memegang meja #5 alur site sebagai **pemegang role `KTT`**, bukan
  sebagai atasan siapa pun — dua hal yang mudah tertukar karena
  jabatannya terdengar paling tinggi di site.

  Pimpinan site karena itu **wajib berada di atas tingkat `MGR`**. Versi
  pertama dokumen ini menamainya "Site Superintendent" pada level `SPV`,
  satu tingkat di **bawah** KTT dan Site HR Manager yang keduanya `MGR` —
  padahal keduanya melapor kepadanya. Untuk KTT salahnya dobel: ia
  diangkat dan disahkan Kepala Inspektur Tambang sebagai pemegang
  otoritas teknis tertinggi di site, jadi secara administratif boleh
  berada di bawah pimpinan site, tapi tidak pernah di bawah seorang
  Superintendent.
- **Lima orang di site tidak punya bawahan sama sekali** — `SGA002`,
  `SGA003`, `SGA005`, `SGA006`, dan `SGA009`. Itu bukan data yang belum
  lengkap: yang memberi mereka peran di alur adalah **role** yang
  dipegangnya (`ADMIN-SECTION`, `HR-ADMIN`, `KTT`), bukan jumlah
  orang di bawahnya. `SGA002` di sini pengaju contoh, dan `SGA009`
  sengaja duduk di department tanpa kepala supaya step "Kepala
  Departemen" yang dilewati ikut terlihat bentuknya.
- **`LOK001` (Department Admin) melapor langsung ke kepala site**, bukan
  ke salah satu supervisor — cakupannya satu department, bukan satu
  section.

---

## Susunan site

| Department | Total | POH | Lokal | Section |
|---|---|---|---|---|
| Site Operations | 11 | 7 | 4 | Site Operations (6) · Hauling (4) · General (1) |
| Plant & Maintenance | 3 | 1 | 2 | Mechanical (2) · Electrical (1) |
| Engineering | 2 | 1 | 1 | Survey (2) |
| Health, Safety & Environment | 1 | 1 | 0 | General (1) |
| Logistics | 1 | 0 | 1 | General (1) |

---

## Tiga orang yang belum bisa mengajukan cutinya sendiri

Sudah diuji sampai Submit sungguhan (bukan cuma pratinjau approver), dan
tiga akun ini **ditolak saat Submit**:

| Akun | Tertahan di | Sebabnya |
|---|---|---|
| `demo.sitehrmanager` (`SGA004`) | Step #4 — HR Manager Site | dia **satu-satunya** pemegang `HR-MANAGER` di Sagea |
| `demo.ktt` (`SGA005`) | Step #5 — KTT Site | dia **satu-satunya** pemegang `KTT` di Sagea |
| `demo.gm` (`HO006`) | Step #1 — Atasan Langsung | dia puncak rantai, `Reports To`-nya memang kosong |

Ini **bukan bug data peragaan**, dan menambah orang tidak menyelesaikannya:
engine sengaja mengeluarkan pengaju dari daftar approver dokumennya
sendiri, dan step #4/#5 memang ditulis **tanpa role cadangan** —
"kalau tidak ada KTT di site itu, yang salah datanya, bukan dokumennya".
Untuk pemegang meja tunggal, aturan yang benar itu berubah jadi jalan
buntu.

Kalau perlu diuji, tiga jalan keluarnya:

1. **Matikan `Wajib` pada step-nya** lewat `Workflow → Approval Steps`.
   Step yang `is_required=False` jadi **SKIPPED beserta alasannya** —
   kotak tanda tangannya tetap tercetak, cuma tidak menahan dokumen.
   Ini yang paling mendekati praktik: cuti KTT memang tidak disetujui
   oleh KTT.
2. **Tambah pemegang role kedua** di lokasi itu lewat
   `Security → User Roles` — masuk akal untuk `HR-MANAGER`, tidak untuk
   `KTT` (satu site satu KTT — yang menjadikannya per-site
   `approver_scope=LOCATION` pada step-nya, bukan kode role-nya).
3. Untuk `HO006`, isi `Reports To`-nya ke atasan di grup. Selama dia
   puncak rantai, cutinya memang tidak punya meja pertama.

Yang **tidak** menolong: login sebagai superuser. Superuser boleh
*memutuskan* dokumen yang sudah berjalan, tapi kegagalannya di sini
terjadi saat **Submit** — sebelum satu kotak tanda tangan pun terbentuk.

---

## Troubleshooting

Gejala di kolom kiri hampir selalu punya sebab di kolom tengah, dan
hampir semuanya **gagal tanpa pesan error**.

| Gejala | Sebab | Perbaikan |
|---|---|---|
| Submit cuti ditolak: "tidak ada approver" | `Reports To` kosong | Isi di tab Organization |
| Submit ditolak padahal `Reports To` terisi | pengaju adalah **satu-satunya** pemegang role di meja itu | Lihat [Tiga orang yang belum bisa mengajukan cutinya sendiri](#tiga-orang-yang-belum-bisa-mengajukan-cutinya-sendiri) |
| Saldo cuti nol untuk pegawai lama | `generate_leave_balances` belum jalan, atau Join Date kosong | Jalankan perintahnya; baca alasannya di kartu saldo |
| Saldo cuti nol untuk pegawai baru | belum genap 12 bulan | **benar** — alasannya tercetak di kartunya |
| Jenis cuti tidak punya saldo sama sekali | tidak ada Leave Policy untuk jenis itu | Memang begitu untuk cuti tak berkuota |
| Layar Roster Setup kosong saat Add Employees | site salah, atau semuanya sudah punya rencana berjalan | Periksa filter Company/Site |
| Jadwal roster terbit tanpa segmen travel | Point of Hire kosong, atau kotanya tidak ada di tabel hari perjalanan policy | Isi POH; periksa tab Travel Days by POH |
| Hari cuti pegawai site terhitung 5 padahal blok off | rosternya belum di-commit | Selesaikan langkah ③ |
| Kolom Late nol di semua baris presensi | Shift kosong di tab Work Arrangement | Isi Shift; lalu `recalculate_attendance` |
| Tingkat Kehadiran 100% terus | `close_attendance` belum pernah jalan | Jalankan perintahnya |
| Dokumen site mendarat di meja Jakarta | Location pegawai salah | Periksa tab Organization |
| Meja #1 site jatuh ke HR, bukan ke Admin Section | section pegawainya tidak punya pemegang `ADMIN-SECTION` | Sengaja — turunannya memang bertingkat. Alasannya tercetak di kotak tanda tangan |
| Tombol Simpan dibalas 403 | role belum punya izin modelnya | `Security → Role Permissions`, atau jalankan ulang `seed_security_roles` |

---

## Membangun ulang dari nol

```bash
# Tenant peragaan berisi pegawai saja — transaksinya kosong
DEMO_PASSWORD=<DEMO_PASSWORD> python manage.py tenant_command seed_demo --reset --employees-only --schema=demo

# Tenant peragaan penuh (roster, dokumen, presensi ikut terisi)
DEMO_PASSWORD=<DEMO_PASSWORD> python manage.py tenant_command seed_demo --reset --schema=demo
```

Yang dibuang `--reset` hanya nomor pegawai berawalan `HO`/`SGA`/`LOK`
beserta dokumennya. Master organisasi, master referensi, dan definisi
alur tidak disentuh.

Untuk menambahkan pegawai saja ke tenant yang masternya sudah berdiri:

```bash
python manage.py tenant_command seed_demo_employees --schema=demo
```

---

## Bacaan lanjutan

- [Menentukan Saldo Cuti](Leave-Balance-Setup.md) — dari data pegawai sampai angka di kartu
- [Leave Request](Leave-Request.md) — rincian jalur cuti
- [Roster Management](Roster-Management.md) — policy, versi, dan penyesuaian
- [Travel Request](Travel-Request.md) — dokumen kepulangan
- [Document Approval](Document-Approval.md) — engine alur persetujuan
- [Employee Action](Employee-Action.md) — perubahan kepegawaian
