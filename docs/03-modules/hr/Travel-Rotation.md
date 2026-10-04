# Travel & Rotation

Alur lengkapnya di **[Travel Request](../../09-business-flows/Travel-Request.md)** dan **[Roster Management](../../09-business-flows/Roster-Management.md)**. Halaman ini peta modulnya.

---

## Dua dokumen yang jangan ditukar

Ini pernah tertukar dan menyeret desain approval ke tempat yang salah.

| | Roster Schedule (`SiteRotation`) | Travel Request |
|---|---|---|
| Apa | **jadwal kerja setahun** | **dokumen pengajuan satu kepulangan** |
| Sifat | alat perencanaan | yang diajukan, disetujui, dibelikan tiket |
| Per orang | satu jadwal | banyak TR setahun |
| Prefix nomor | `RST` | `TR` |

`TravelRequest.rotation_period` **nullable** — roster bukan syarat TR.

---

## Modul

| `framework_module` | Model | Halaman FE |
|---|---|---|
| `hr/travel-requests` | `TravelRequest` | ✅ |
| `hr/travel-request-purposes` | `TravelRequestPurpose` | 🔒 tabel inline |
| `hr/travel-arrangements` | `TravelArrangement` | 🔒 tabel inline |
| `hr/site-rotations` | `SiteRotation` | ✅ |
| `hr/rotation-periods` | `RotationPeriod` | 🔒 tabel inline |
| `hr/roster-setups`, `hr/roster-setup-lines` | dokumen setup massal | ✅ |
| `hr/roster-adjustments` | `RosterAdjustment` | ✅ |
| `hr/rotation-credits` | ledger kredit | ✅ |
| `hr/roster-policies` | `RosterPolicy` | ✅ |
| `hr/roster-travel-days` | `RosterTravelDay` | 🔒 tabel inline |
| `references/hr/rotation-purposes` | `RotationPurpose` | ✅ |

---

## Dua jalur roster, keduanya hidup

| | Lama | Baru |
|---|---|---|
| Jangkar | `RosterCrew.cycle_start_date` | `EmploymentAssignment.roster_cycle_start` |
| Yang menentukan pola | `RosterCrew` | **`RosterPolicy`** |
| Generate | membangun ulang **seluruh** dokumen | tidak pernah menyentuh baris yang sudah lewat |

Di tabel Roster Schedule keduanya berdampingan — itu sebabnya ada kolom **Roster Policy**, supaya rencana dari jalur baru tidak terbaca seperti data yang belum diisi.

Pemetaan pegawai lama: `tenant_command migrate_roster_assignments` (`--dry-run`), yang **melewati yang ambigu** alih-alih menebak.

---

## Aturan yang paling sering salah dipahami

### `cycle_travel_days` = TOTAL pulang-pergi

Bukan sekali jalan. `2` berarti sehari keluar + sehari kembali:

```
cycle_length = work + off + travel        (bukan work + off + 2 × travel)
```

Angka ganjil dipecah **tidak rata, kelebihannya ke sisi keluar** (3 → 2 keluar, 1 kembali).

!!! bug "Bug yang melesetnya menumpuk sepanjang tahun"
    `apply_cycle_pattern` dulu memakai `work + off + travel * 2` saat menurunkan `start_date` dari jangkar crew — tanggal mulai otomatis mendarat di tanggal yang **bukan** awal siklus crew mana pun.

    Hanya kena dokumen baru yang `start_date`-nya dikosongkan.

### Travel tidak memendekkan blok kerja

`travel_out_counts_as_roster_day` / `travel_in_counts_as_roster_day` hanya memengaruhi **rekap** `on_site_days`. Pegawai 42/14 yang dua hari di kapal tetap menjalani 42 hari di site.

### Hari travel ditentukan jarak, bukan gelombang

POH Makassar 2 hari, Yogyakarta/Bandung/Luwuk Banggai 3 hari — walau satu crew dan satu pola. Berjenjang:

```
EmploymentAssignment.travel_days_override
  → RosterTravelDay (site, POH)
    → RosterPolicy.default_travel_days
      → 0
```

!!! danger "`travel_days_for()` wajib dioper `policy=`"
    Tanpa itu ia me-resolve ulang dan bisa tidak menemukan satu pun — hari perjalanan jatuh ke nol. **Jadwalnya tetap terbit, cuma tanpa satu pun segmen travel.** Ketahuan lewat test, bukan lewat layar.

### `RotationPurpose` bukan `LeaveType`

Master tersendiri: **Field Break** adalah blok off rosternya sendiri dan tidak memotong saldo; **Cuti Tahunan** memotong. `deducts_leave` yang jadi penentu, dan `leave_type` **wajib** diisi begitu penanda itu menyala.

Menaruh Field Break di `LeaveType` membuatnya ikut muncul di dropdown modul Cuti dan bisa dibuatkan saldo.

### Tanggal penerbangan hanya di TR

`TravelArrangement` menggantikan `RotationTravel` yang dulu menempel ke blok jadwal. Jadwal hanya **menghitung** perkiraan jendela travel.

!!! danger "Jangan kembalikan baris travel ke roster"
    Dua tempat = dua tanggal keberangkatan untuk penerbangan yang sama.

### Satu baris `TravelArrangement` = satu **etape**

Bukan satu arah. POH Jakarta: 13 Sep Jakarta→Sorong, 14 Sep Sorong→Gebe. POH Makassar menempuh dua etape yang sama **di hari yang sama**.

Constraint lama yang memaksa satu baris per arah membuat rute transit jatuh ke satu kolom teks yang tidak bisa dilaporkan.

---

## Alur site: enam meja

Admin Section → Admin HR Site → Atasan → HR Manager Site → KTT → **HRGA**.

HRGA di posisi terakhir, dan itu yang membuat "Issued By" jujur: step tidak punya efek samping sendiri, `on_complete` baru jalan saat **seluruh** alur selesai. Di posisi mana pun selain #6, labelnya berbohong — dan tiket yang terlanjur dibeli lalu ditolak KTT adalah uang yang hilang.

Rantai yang sama dipakai TR **dan** Cuti (dua definisi, `steps` identik, beda `document_type`).

Detail: [Document Approval](../../09-business-flows/Document-Approval.md#alur-site-enam-meja).

---

## Perintah

```bash
tenant_command seed_roster_policy        # aturan + kota POH
tenant_command seed_roster_demo          # data uji
tenant_command report_rotation_cycles    # cetak tabel periode + rekap setahun
tenant_command extend_roster_horizon --threshold-days=60 --months=6 --dry-run
```

`extend_roster_horizon` **tidak butuh approval** — ia menempel halaman baru di bawah kalender, bukan mencetak ulang kalendernya. Belum dijadwalkan otomatis.

---

## Yang belum ada

- `travel_day_mode = ACTUAL_ITINERARY` — kolomnya tersimpan, rekonsiliasi rencana↔realisasi belum ada
- Layar pembanding back-to-back
- Eksekusi kedaluwarsa kredit (`credit_expiry_months`)
- Notifikasi H-7 (`request_lead_days`/`notify_lead_days` tersimpan, belum dibaca)
- **Cetak PDF TR** — approval sudah jalan, render kotak tanda tangan dari `approval.steps` belum
- **Terbuka:** cuti tahunan di dalam blok off memotong 0 hari, sehingga label barisnya tidak berpengaruh apa-apa
