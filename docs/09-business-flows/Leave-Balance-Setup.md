# Menentukan Saldo Cuti: dari Data Employee sampai Kartu Saldo

Dokumen ini menjawab satu pertanyaan sampai tuntas: **angka di kartu cuti
seseorang itu datang dari mana, dan bagaimana menerbitkannya.**

Acuan sepanjang dokumen: tenant `demo` per **19 Agustus 2026**, berisi
26 pegawai (`seed_demo --employees-only`) dan **nol baris saldo cuti**.
Seluruh angka di bawah adalah hasil `--dry-run` sungguhan terhadap data
itu, bukan contoh karangan.

> Tidak ada seed di sini. Setiap langkah dijalankan sendiri — itu memang
> yang mau diuji.

---

## 0. Konsep: satu kartu, tiga kantong

Satu baris `LeaveBalance` = **satu pegawai × satu jenis cuti × satu
tahun**. Isinya bukan satu angka, melainkan tiga pemberian yang lahir
dari tempat berbeda, plus koreksi manusia:

```
┌─ KARTU SALDO — Bimo Nugroho · Annual Leave · 2026 ─────────────┐
│                                                                │
│  PEMBERIAN                                                     │
│    entitlement       jatah tahun berjalan   ← Leave Policy     │
│    carried_over      sisa tahun lalu        ← carry over       │
│    opening_balance   saldo dari sistem lama ← dokumen migrasi  │
│    adjustment        koreksi manual         ← manusia          │
│                                                                │
│  PENGURANG                                                     │
│    used                      ← dijumlah ulang dari catatan cuti│
│    carried_over_forfeited    ← hangus                          │
│    opening_forfeited         ← hangus                          │
│                                                                │
│  remaining = pemberian − pengurang                             │
└────────────────────────────────────────────────────────────────┘
```

**Tiap kolom punya satu pemilik, dan tidak ada yang menimpa milik orang
lain.** Ini yang membuat perhitungan ulang aman dijalankan kapan saja:

| Kolom | Ditulis oleh | Boleh diketik tangan? |
|---|---|---|
| `entitlement` | `LeaveBalanceGenerator` dari `LeavePolicy` | **tidak** — ditimpa tiap generate |
| `carried_over` | `carry_over_leave_balances` | **tidak** — ditimpa tiap carry over |
| `opening_balance` | dijumlah ulang dari `LeaveOpeningBalance` | **tidak** — ditimpa tiap sinkronisasi |
| `adjustment` | **manusia** | **ya** — satu-satunya yang aman |
| `used` | dijumlah ulang dari catatan `EmployeeLeave` | tidak |

> Kalau ada yang bertanya "kenapa tambahan 3 hari yang saya ketik hilang":
> hampir selalu karena diketik ke `entitlement`, bukan ke `adjustment`.

---

## 1. Apa yang menentukan angkanya

### 1.1 Empat kolom di data pegawai

Jatah dihitung dari **data pegawai**, bukan diketik. Empat kolom ini
yang dibaca — tiga di tab **Current Employment**, satu di tab
**Organization**:

| Kolom | Tab | Perannya |
|---|---|---|
| **Join Date** | Current Employment | menentukan **kapan** ia berhak (masa tunggu) |
| Employee Group | Current Employment | penyaring aturan mana yang berlaku |
| Employment Type | Current Employment | penyaring aturan mana yang berlaku |
| Company | Organization | penyaring aturan mana yang berlaku |

**Join Date kosong = jatah nol**, dengan alasan tertulis
("Join Date pegawai belum diisi, jadi masa tunggu tidak bisa dihitung").
Bukan error — pegawai memang boleh disimpan tanpa tanggal masuk, mis.
hasil import massal yang klasifikasinya menyusul.

### 1.2 Leave Policy — aturannya

`HR → Masters → Leave Policy` (`/hr/leave-policies`). Tenant ini punya
**satu** baris:

| Kolom | Isi `ANNUAL-STD` | Artinya |
|---|---|---|
| Leave Type | `ANNUAL` | jenis cuti yang diatur |
| Entitlement Days | **12,00** | jatah penuh satu periode |
| Accrual | `upfront` | diberikan sekaligus di awal periode |
| Period Basis | `calendar` | periode = 1 Jan – 31 Des |
| Eligible After Months | **12** | masa tunggu sejak Join Date |
| Prorate First Period | **ya** | periode pertama dihitung sebagian |
| Allow Carry Over | **tidak** | sisa tidak dibawa ke tahun depan |
| Company / Group / Type | *(kosong)* | **berlaku untuk semua** |

> **Kosong berarti "berlaku untuk semua", bukan "tidak berlaku".** Ini
> jebakan paling gampang di layar setting, dan sama untuk seluruh policy
> di sistem ini (Roster, Attendance, Employee Action, Employee Data).

### 1.3 Kalau ada lebih dari satu aturan

Yang menang **bukan** yang barisnya paling atas, melainkan yang paling
**khusus** — dihitung lewat skor `specificity`:

```
company terisi   +4
employee_group   +2      →  skor tertinggi yang dipakai
employment_type  +1
```

Jadi aturan yang menyebut *company* mengalahkan yang global, dan yang
menyebut *Employee Group* mengalahkan yang tidak. Jatah cuti seseorang
tidak boleh bergantung pada nomor `id` di database.

**Contoh yang lazim dipakai klien tambang:**

| Kode | Sasaran | Jatah | Skor | Berlaku untuk |
|---|---|---|---|---|
| `ANNUAL-STD` | *(kosong)* | 12 | 0 | semua orang |
| `ANNUAL-LOCAL` | Group = `LOCAL` | 14 | 2 | tenaga lokal site |
| `ANNUAL-MGMT` | Group = `MANAGEMENT` | 18 | 2 | manajemen |

Dengan tiga baris itu, `LOK002` dapat 14 hari, `SGA001` dapat 18, dan
sisanya 12 — tanpa satu pun baris saldo diketik tangan.

### 1.4 Jenis cuti yang tidak punya policy

**Tidak menghasilkan baris saldo sama sekali.** Cutinya tetap bisa
diajukan dan dicatat, cuma tidak ada angka yang dipotong.

Itu perilaku yang benar untuk cuti tak berkuota — sakit, melahirkan,
duka, menikah. Undang-undang tidak mengatur kuota hari sakit per tahun
(yang diatur skala upah selama sakit berkepanjangan), jadi angka apa pun
di sana adalah karangan. Dari 10 jenis cuti di master, **hanya `ANNUAL`
yang punya policy** — sembilan sisanya sengaja tidak.

---

## 2. Rumus jatah, langkah demi langkah

```
        Ada Leave Policy untuk jenis cuti ini?
                    │
         tidak ─────┴───── ya
           │                │
    tidak ada baris    Join Date terisi?
        saldo               │
                 tidak ─────┴───── ya
                   │                │
              0 hari,        eligible_from = Join Date + eligible_after_months
          "Join Date belum          │
             diisi"          eligible_from > 31 Des tahun itu?
                                    │
                            ya ─────┴───── tidak
                             │              │
                      0 hari,        eligible_from ≤ 1 Jan tahun itu?
                  "Baru berhak <tgl>"       │
                                    ya ─────┴───── tidak
                                     │              │
                              JATAH PENUH    PRORATA n/12
                                 12 hari      n = jumlah bulan dari
                                              eligible_from s/d 31 Des
```

**Bulannya dibulatkan ke atas.** Yang berhak tanggal 15 Agustus tetap
kebagian Agustus penuh — membulatkan ke bawah membuat orang kehilangan
sebulan hanya karena tanggal masuknya lewat tanggal 1.

### Empat contoh nyata dari tenant ini

**① Jatah penuh** — `HO001` Sarah Wibowo, masuk **7 Jan 2019**

```
eligible_from = 2019-01-07 + 12 bulan = 2020-01-07
2020-01-07 ≤ 2026-01-01  →  sudah berhak sebelum periode dimulai
                         →  12,00 hari
```

**② Prorata** — `HO003` Bimo Nugroho, masuk **15 Ags 2025**

```
eligible_from = 2025-08-15 + 12 bulan = 2026-08-15
2026-08-15 ada di dalam 2026, dan sesudah 1 Jan  →  prorata
n = Ags, Sep, Okt, Nov, Des = 5 bulan
12,00 × 5/12 = 5,00 hari
```

> Hari ini **19 Agustus 2026** — Bimo baru berhak **empat hari yang
> lalu**. Sebelum 15 Agustus, kartunya berbunyi nol dengan alasan
> "Baru berhak 2026-08-15".

**③ Belum berhak tahun ini** — `SGA006` Eko Prasetyo, masuk **1 Jul 2026**

```
eligible_from = 2027-07-01  →  lewat 31 Des 2026
2026: 0 hari, "Baru berhak 2027-07-01 — 12 bulan sejak masuk 2026-07-01"
2027: prorata 6/12 = 6,00 hari   (Jul s/d Des)
```

**④ Prorata pendek** — `LOK004` Sultan Ahmad, masuk **10 Nov 2025**

```
eligible_from = 2026-11-10
n = Nov, Des = 2 bulan  →  12,00 × 2/12 = 2,00 hari
```

> **Catatan `upfront`:** karena akrualnya di depan, dua hari itu sudah
> **ada di kartunya sekarang** walau ia baru berhak November. Pembatasan
> "belum boleh dipakai sampai bulannya tiba" belum dibuat — sengaja,
> karena butuh aturan "boleh minus atau tidak" yang juga belum ada.
> Kalau ini penting untuk klien Anda, ubah `Accrual` jadi bulanan dan
> catat batasannya sebagai kebutuhan tersendiri.

---

## 3. Langkah menerbitkannya — hari ini

### Langkah 1 — Pastikan prasyaratnya terisi

Buka `HR → Employees`, periksa **Join Date** terisi untuk semua orang.
Cara cepat: tambahkan kolom Join Date ke tabel lalu urutkan menaik —
yang kosong berkumpul di atas.

Di tenant ini ke-26 pegawai sudah punya Join Date, jadi langkah ini
lewat.

### Langkah 2 — Periksa aturannya

`HR → Masters → Leave Policy`. Kalau semua pegawai memang 12 hari,
`ANNUAL-STD` sudah cukup dan tidak ada yang perlu diubah.

Kalau jatahnya berbeda per golongan, **tambah baris** (jangan mengubah
`ANNUAL-STD` — ia jaring untuk yang tidak masuk golongan mana pun), lalu
isi Scope-nya. Lihat §1.3.

### Langkah 3 — Lihat hasilnya dulu, tanpa menulis apa pun

```bash
python manage.py tenant_command generate_leave_balances \
    --year=2026 --dry-run --verbose-rows --schema=demo
```

`--dry-run` **tidak menyentuh database sama sekali**. `--verbose-rows`
mencetak satu baris per pegawai beserta alasannya — dan alasan itulah
yang dibaca kalau ada angka yang tidak sesuai dugaan.

Baca keluarannya sebelum lanjut. Angka nol yang **ada alasannya** normal;
angka nol berbunyi "Belum ada Leave Policy untuk ANNUAL" berarti
Langkah 2 belum beres.

### Langkah 4 — Jalankan

```bash
python manage.py tenant_command generate_leave_balances --year=2026 --schema=demo
python manage.py tenant_command generate_leave_balances --year=2027 --schema=demo
```

**Tahun depan ikut diterbitkan sekarang**, dan itu bukan kelebihan:
pegawai yang masuk pertengahan tahun ini baru berhak tahun depan, dan
HR perlu bisa menjawab "kapan saya mulai punya jatah" hari ini juga.

Aman diulang. Yang ditulis ulang hanya `entitlement`; `adjustment`,
`used`, dan `opening_balance` tidak disentuh.

### Langkah 5 — Verifikasi di layar

`HR → Attendance & Leave → Leave Balance` (`/hr/leave-balances`).
Harus muncul **26 baris untuk 2026** dan 26 untuk 2027 — satu per
pegawai, semuanya jenis `ANNUAL`.

### Jalan pintas: lewat form Employee

Saldo juga **terbit sendiri** begitu Join Date disimpan lewat form
Employee (`EmploymentService.save()` memanggil generator untuk tahun
berjalan + tahun depan). Jadi untuk **satu** pegawai baru, tidak perlu
menjalankan perintah apa pun — buka kartunya, simpan, kartu saldonya
muncul.

Perintah di §Langkah 4 tetap dipakai untuk:

- pergantian tahun,
- sesudah Leave Policy diubah (pegawai lama tidak ikut berubah sendiri),
- tenant yang pegawainya masuk lewat import massal.

---

## 4. Yang akan keluar untuk 26 pegawai ini

Hasil `--dry-run` per 19 Agustus 2026. Kolom **2026** dan **2027**
adalah `entitlement`; kolom Alasan adalah teks yang benar-benar tercetak
di kartunya.

### Kantor Pusat

| No | Nama | Join Date | 2026 | 2027 | Alasan (2026) |
|---|---|---|---|---|---|
| `HO006` | Adrian Mahendra | 2017-02-01 | **12,00** | 12,00 | jatah penuh |
| `HO001` | Sarah Wibowo | 2019-01-07 | **12,00** | 12,00 | jatah penuh |
| `HO005` | Farah Anindita | 2018-04-16 | **12,00** | 12,00 | jatah penuh |
| `HO002` | Hesti Rahayu | 2021-06-01 | **12,00** | 12,00 | jatah penuh |
| `HO007` | Rangga Pratomo | 2023-09-11 | **12,00** | 12,00 | jatah penuh |
| `HO008` | Yulia Kartika | 2024-01-15 | **12,00** | 12,00 | jatah penuh |
| `HO003` | Bimo Nugroho | 2025-08-15 | **5,00** | 12,00 | prorata 5/12 — berhak 2026-08-15 |
| `HO004` | Clara Wijaya | 2026-03-02 | **0** | 10,00 | berhak 2027-03-02 |

### Site — Point of Hire

| No | Nama | Join Date | 2026 | 2027 | Alasan (2026) |
|---|---|---|---|---|---|
| `SGA010` | Yusuf Maulana | 2019-07-22 | **12,00** | 12,00 | jatah penuh |
| `SGA001` | Rinaldo Saputra | 2020-02-03 | **12,00** | 12,00 | jatah penuh |
| `SGA007` | Ferry Wibisono | 2021-03-08 | **12,00** | 12,00 | jatah penuh |
| `SGA004` | Citra Halimah | 2021-11-01 | **12,00** | 12,00 | jatah penuh |
| `SGA002` | Ahmad Sudrajat | 2022-05-09 | **12,00** | 12,00 | jatah penuh |
| `SGA009` | Novita Sari | 2022-10-03 | **12,00** | 12,00 | jatah penuh |
| `SGA008` | Gilang Ramadhan | 2023-06-19 | **12,00** | 12,00 | jatah penuh |
| `SGA005` | Dedi Kurniawan | 2024-04-22 | **12,00** | 12,00 | jatah penuh |
| `SGA003` | Bayu Prakoso | 2025-08-15 | **5,00** | 12,00 | prorata 5/12 — berhak 2026-08-15 |
| `SGA006` | Eko Prasetyo | 2026-07-01 | **0** | 6,00 | berhak 2027-07-01 |

### Site — tenaga lokal

| No | Nama | Join Date | 2026 | 2027 | Alasan (2026) |
|---|---|---|---|---|---|
| `LOK005` | Umar Sahdan | 2021-09-06 | **12,00** | 12,00 | jatah penuh |
| `LOK001` | Rustam Hasan | 2022-02-14 | **12,00** | 12,00 | jatah penuh |
| `LOK006` | Taufik Ode | 2023-01-23 | **12,00** | 12,00 | jatah penuh |
| `LOK002` | Jufri Sangaji | 2023-04-03 | **12,00** | 12,00 | jatah penuh |
| `LOK007` | Hamid Latif | 2024-05-27 | **12,00** | 12,00 | jatah penuh |
| `LOK003` | Rahmat Tidore | 2024-08-19 | **12,00** | 12,00 | jatah penuh |
| `LOK004` | Sultan Ahmad | 2025-11-10 | **2,00** | 12,00 | prorata 2/12 — berhak 2026-11-10 |
| `LOK008` | Nurlela Wahab | 2026-04-06 | **0** | 9,00 | berhak 2027-04-06 |

**Rekap 2026:** 20 orang jatah penuh (12,00) · 2 orang prorata 5,00 ·
1 orang prorata 2,00 · 3 orang nol dengan alasan tertulis.
Total jatah terbit **252,00 hari** untuk 26 pegawai.

> Perhatikan **`LOK003` masuk 19 Agustus 2024** — tepat dua tahun lalu
> hari ini. Ia sudah berhak sejak 19 Agustus 2025, jadi 2026 penuh.
> Kalau tanggal masuknya setahun lebih muda, angkanya jadi 5,00 seperti
> Bimo — selisih satu tahun pada tanggal yang sama.

---

## 5. Bagaimana `used` terisi

`used` **tidak pernah diketik**. `EmployeeLeaveService` menjumlahkannya
ulang dari seluruh catatan `EmployeeLeave` milik pegawai itu setiap kali
ada cuti dibuat, diubah, dihapus, atau berpindah status.

**Penjumlahan ulang, bukan tambah-kurang inkremental** — angka yang
ditambah sedikit-sedikit tidak bisa dibuktikan benar, dan begitu hanyut
tidak ada cara mengembalikannya.

### Status mana yang memotong

| Status | Memotong saldo? |
|---|---|
| `DRAFT` | tidak |
| `SUBMITTED` | **tidak** — belum disetujui, belum boleh mengurangi hak orang |
| `APPROVED` | **ya** |
| `RECORDED` | **ya** — dicatat HR, sudah terjadi |
| `REJECTED` / `CANCELLED` | tidak |

### Berapa hari yang dipotong

Bukan selisih tanggal. `LeaveDayCalculator` menghitung **hari kerja yang
hilang**, dan cabangnya ditentukan pola kerja pegawainya:

| Pegawai | Sumber hitungan |
|---|---|
| punya roster (POH, sesudah Roster Setup) | blok kerja/off di jadwalnya — akhir pekan & libur nasional **tidak** dikecualikan |
| lainnya (HO & tenaga lokal) | `WorkCalendar` — akhir pekan & libur nasional dikecualikan |

**Contoh terverifikasi**, cuti 14–18 Agustus 2026 (**5 hari kalender**:
Jum, Sab, Min, Sen, Sel — dan 17 Agustus libur nasional):

| Pegawai | Kalender | Dipotong | Kenapa |
|---|---|---|---|
| `HO003` Bimo (HO) | `OFFICE-2026`, Sen–Jum | **2,00** | Sab & Min bukan hari kerja, 17 Ags libur |
| `LOK002` Jufri (lokal site) | `LOCATION-3-2026`, 7 hari | **4,00** | site bekerja Sab & Min; 17 Ags tetap libur |
| `SGA002` Ahmad (POH, roster belum ada) | jatuh ke kalender site | **4,00** | sesudah Roster Setup, dihitung dari blok on/off |

Cuti 7–11 September 2026 (Sen–Jum, tanpa libur) memotong **5,00** untuk
ketiganya.

**`total_days` = 0 itu sah, bukan error.** Pegawai roster yang cuti saat
blok off-nya tidak kehilangan hari kerja apa pun. Itu jawaban desain
untuk "boleh ambil cuti tahunan saat hari off?" — boleh, dan tidak
memakan saldo.

### Saldo boleh minus

Belum ada penjagaan over-draw. Kelebihan pakai muncul sebagai
`advance_used` (pemakaian yang tidak punya kantong) — dan itu justru
yang membuat kartu bersaldo −3 bisa dijelaskan, bukan terbaca seperti
salah hitung.

---

## 6. Tiga sumber angka lainnya

### 6.1 `opening_balance` — tenant yang pindah dari sistem lama

> Langkah lengkapnya — termasuk jebakan dobel hitung saat go-live jatuh
> di tengah tahun, dan contoh file import yang sudah diuji — ada di
> [Go-Live Cuti](Leave-Go-Live.md).

Klien migrasi datang membawa **saldo, bukan histori**: "Andi masuk Maret
2024, sisa cutinya 7 hari" — sementara catatan cuti tahun-tahun
sebelumnya tidak lengkap dan tidak akan pernah lengkap.

**Jangan** menyelesaikannya dengan dua jalan pintas yang sama-sama salah:

- membuat `EmployeeLeave` fiktif untuk mengarang pemakaiannya, atau
- menerbitkan `LeaveBalance` tahun 2022–2025 yang jatahnya tidak bisa
  dijelaskan.

Yang benar: **satu titik awal bertanggal**, lalu seluruh transaksi
sesudahnya kembali lewat jalur normal.

**Layar:** `HR → Attendance & Leave → Leave Opening Balance`
(`/hr/leave-opening-balances`), atau import massal lewat
`/hr/leave-opening-balances/import`.

| Kolom | Isi |
|---|---|
| Employee · Leave Type | satu baris per pasangan, ditegakkan constraint |
| Opening Date | tanggal go-live — bukan 1 Januari |
| Opening Days | sisa menurut sistem lama |

`LeaveBalance.opening_balance` **dijumlah ulang** dari dokumen ini —
jangan pernah mengetiknya langsung ke kartu.

> **Batas satu baris per pegawai per jenis cuti itu disengaja.** Tanpa
> batas itu, dalam tiga bulan ia berubah jadi cara menambah saldo
> sehari-hari — dan koreksi harian tempatnya `adjustment`, yang memang
> dibuat untuk itu.

### 6.2 `adjustment` — koreksi manual

Satu-satunya kolom yang aman diketik tangan di kartu saldo. Boleh
positif maupun negatif. Dipakai untuk hal yang tidak bisa diturunkan
dari aturan mana pun: "tambahan 3 hari karena lembur Lebaran",
"potongan 1 hari, sudah dibayar tunai".

**Tidak pernah disentuh generator** — itu yang membuat
`generate_leave_balances` aman dijalankan berapa kali pun.

Isi juga kolom **Notes**-nya. Angka koreksi tanpa alasan tertulis adalah
pertanyaan yang akan sampai ke HR enam bulan lagi, saat orang yang
mengetiknya sudah lupa.

### 6.3 `carried_over` — sisa tahun lalu

**Mati di tenant ini** (`Allow Carry Over` = tidak pada `ANNUAL-STD`),
jadi sisa 2026 hangus pada 31 Desember dan 2027 mulai dari jatah baru.

Untuk menyalakannya, di Leave Policy tab **Carry Over**:

| Kolom | Artinya |
|---|---|
| Allow Carry Over | nyalakan |
| Carry Over Max Days | batas atas yang boleh dibawa (mis. 6) |
| Carry Over Expiry Months | berapa bulan sisa bawaan berlaku (mis. 6 → hangus 30 Juni) |
| Carry Over Reminder Days | tonggak pengingat, bawaan `30,14,7` |

Lalu jalankan **sesudah** jatah tahun barunya terbit:

```bash
python manage.py tenant_command generate_leave_balances  --year=2027 --schema=demo
python manage.py tenant_command carry_over_leave_balances --year=2027 --schema=demo
```

**Urutannya wajib begitu.** Baris saldo tujuan harus sudah ada — carry
over tidak membuatnya, dan yang tidak ketemu dilaporkan
`skipped_no_target`, bukan dibuat diam-diam.

**Manual, bukan otomatis tengah malam pergantian tahun.** Keduanya
mengubah angka yang tercetak di kartu cuti orang; perintah yang berjalan
sendiri akan memindahkan saldo pegawai yang datanya belum selesai
dirapikan, dan hasilnya baru ketahuan saat ada yang mengajukan cuti di
Februari.

Tanggal hangus dihitung dari **1 Januari tahun itu**, bukan dari tanggal
perintahnya dijalankan — HR yang menjalankan carry over di bulan Maret
tidak boleh membuat batas hangusnya mundur tiga bulan dibanding tenant
yang tepat waktu.

### 6.4 Kantong mana yang terpakai duluan

Begitu satu kartu punya lebih dari satu kantong, "cuti ini menggerus
yang mana" jadi pertanyaan nyata — dan tanpa jawabannya penghangusan
tidak bisa dieksekusi sama sekali.

**Aturannya: yang paling cepat hangus dipakai lebih dulu.**

```
opening_balance   (hangus paling awal)   ──┐
carried_over      (hangus akhir Juni)      ├── dipakai berurutan
entitlement       (tidak punya tanggal hangus) ┘
advance_used      ← kelebihan pakai, tidak punya kantong
```

Kalau dibalik, setiap orang kehilangan bawaannya walau cutinya banyak,
dan tidak ada yang bisa menjelaskan kenapa.

Yang hangus **tidak mengurangi kolom pemberiannya** — ia dicatat di
`carried_over_forfeited` / `opening_forfeited`, dan `remaining` yang
mengurangkannya. Sebabnya keras: `carried_over` ditimpa ulang tiap carry
over dijalankan dan `opening_balance` dijumlah ulang dari dokumen
migrasi, jadi hari yang dikurangi di sana akan **hidup lagi** pada
sinkronisasi berikutnya.

Urutan cuti dinilai dari `(start_date, pk)` — bukan `pk` saja. Kalau
diurutkan `pk`, mengoreksi tanggal satu cuti lama akan memindahkan
kantong seluruh cuti sesudahnya, dan jumlah hari hangus seseorang
berubah tanpa ada yang menyentuh datanya.

---

## 7. Membaca kartu saldo

```
remaining = entitlement + carried_over + opening_balance + adjustment
          − used − carried_over_forfeited − opening_forfeited
```

Contoh `HO003` Bimo Nugroho, 2026, sesudah mengambil cuti
14–18 Agustus:

| Kolom | Nilai | Dari mana |
|---|---|---|
| entitlement | 5,00 | prorata 5/12, berhak 15 Ags 2026 |
| carried_over | 0,00 | carry over mati di `ANNUAL-STD` |
| opening_balance | 0,00 | bukan tenant migrasi |
| adjustment | 0,00 | belum ada koreksi |
| used | 2,00 | 5 hari kalender − Sab/Min − 17 Ags |
| **remaining** | **3,00** | |

Kolom rincian per kantong (`opening_used`, `carried_over_used`,
`advance_used`) sudah terisi di database tapi **`table=False`** di layar
daftar — enam kolom angka berjejer membuat tabelnya harus digulir ke
samping. Keduanya terbaca saat barisnya dibuka.

---

## 8. Troubleshooting

| Gejala | Sebab | Perbaikan |
|---|---|---|
| Layar Leave Balance kosong sama sekali | `generate_leave_balances` belum dijalankan | §3 Langkah 4 |
| Satu pegawai tidak punya baris | Join Date kosong | isi di tab Current Employment; saldonya terbit sendiri saat disimpan |
| Semua nol, alasan "Belum ada Leave Policy" | policy jenis cuti itu belum dibuat | §1.2 |
| Nol untuk pegawai baru | belum genap masa tunggu | **benar** — alasannya tercetak di kartunya |
| Jenis cuti tertentu tidak punya baris | memang tidak ada policy-nya | **benar** untuk cuti tak berkuota (§1.4) |
| Jatah tidak berubah setelah policy diedit | policy hanya dibaca saat generate | jalankan ulang `generate_leave_balances` |
| Koreksi manual hilang setelah generate | diketik ke `entitlement` | pindahkan ke `adjustment` (§6.2) |
| Saldo migrasi hilang | diketik ke `entitlement`/`opening_balance` langsung | pakai dokumen Leave Opening Balance (§6.1) |
| Potongan lebih kecil dari jumlah hari cuti | akhir pekan/libur dikecualikan | **benar** — §5 |
| Pegawai site memotong lebih banyak dari pegawai kantor | kalender site 7 hari kerja | **benar** — §5 |
| Cuti disetujui tapi `used` tidak naik | status berhenti di `SUBMITTED` | selesaikan approval-nya |
| `remaining` minus | over-draw, muncul sebagai `advance_used` | belum ada penjagaannya — §5 |
| Carry over jalan tapi nol semua | `Allow Carry Over` mati, atau jatah tahun tujuan belum terbit | §6.3 |

---

## 9. Yang belum ada

Supaya tidak dicari-cari:

- **Penjadwalan otomatis penghangusan.** Perintahnya sudah ada,
  entri Celery Beat-nya belum.
- **Penjagaan over-draw.** Saldo boleh minus; kalau perlu dibatasi,
  tempatnya `EmployeeLeaveService`, bukan model.
- **Pembatasan pemakaian per bulan berjalan** untuk akrual bulanan.
- **Layar rincian per kantong** di daftar saldo (kolomnya terisi,
  `table=False`).

---

## Bacaan lanjutan

- [Urutan Entry: dari Employee sampai Cuti](Employee-Onboarding-Flow.md) — langkah sebelum dan sesudah dokumen ini
- [Leave Request](Leave-Request.md) — dua jalur cuti dan alur persetujuannya
- [Roster Management](Roster-Management.md) — kenapa pegawai roster dihitung berbeda
