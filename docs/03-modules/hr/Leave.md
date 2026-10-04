# Leave

Alur lengkapnya di **[Business Flows → Cuti](../../09-business-flows/Leave-Request.md)**. Halaman ini ringkasan modul + masternya.

!!! note "Saldo awal migrasi, carry over, dan alokasi FIFO ada di halaman lain"
    Kartu saldo punya **tiga kantong** — jatah tahun berjalan, sisa tahun lalu, dan saldo
    awal go-live — dan yang menentukan kantong mana yang tergerus lebih dulu adalah
    alokasi FIFO. Uraiannya di **[Saldo Awal & Pengecualian Presensi](Leave-Opening-Attendance-Exception.md)**.

---

## Dua jalur di satu tabel

| Jalur | Status awal | Approval |
|---|---|---|
| **Pencatatan** — HR mengetik cuti yang sudah terjadi, atau TR menerbitkannya | `RECORDED` | tidak |
| **Pengajuan** — pegawai membuat sendiri | `DRAFT` → `SUBMITTED` | ya |

Memisahkannya jadi dua tabel akan membuat kartu cuti seseorang harus dijumlahkan dari dua sumber.

---

## Modul

| `framework_module` | Model |
|---|---|
| `hr/leave` | `EmployeeLeave` |
| `hr/leave-balances` | `LeaveBalance` |
| `hr/leave-policies` | `LeavePolicy` |
| `references/hr/leave-types` | `LeaveType` |
| `references/hr/leave-reasons` | `LeaveReason` |

!!! note "`framework_module` Leave Policy sengaja `hr/leave-policies`"
    Bukan `references/hr/...`, walau endpoint API-nya di `/api/administration/references/hr/leave-policies/`.

    `framework_module` menentukan **rute frontend**. Saat masih `references/hr/...` sementara halamannya di `/hr/masters/...`, tombol Create dan Edit **404** walau semua berkasnya ada.

---

## Perhitungan hari: dua cabang

`LeaveDayCalculator` memilih cabang dari pola kerja pegawai:

| | Pegawai HO | Pegawai site |
|---|---|---|
| Sumber | `WorkCalendar` berlapis | blok kerja roster |
| Akhir pekan & libur nasional | **dikecualikan** | **tidak** — rosternya sendiri yang jadi kalender |

Cuti 14–18 Agustus 2026 (5 hari kalender): HO memotong **2 hari**, site memotong **5 hari**.

!!! danger "`total_days = 0` itu sah"
    Pegawai roster yang cuti saat blok off-nya memotong **nol** hari. Validasi hanya menolak nilai **negatif**. Jangan kembalikan jadi `> 0`.

Isian manual **selalu menang** — ada kasus yang tidak bisa disimpulkan dari kalender.

---

## Saldo

`LeaveBalance.used` **disimpan** (supaya bisa disortir/difilter) dan **dijumlahkan ulang penuh** dari record `EmployeeLeave` tiap perubahan — bukan inkremental. Penjumlahan ulang tidak bisa hanyut.

`LEAVE_DEDUCTING_STATUSES` = `RECORDED` + `APPROVED`. `SUBMITTED` **tidak** memotong.

**Saldo boleh minus.** Belum ada penjagaan over-draw; kalau nanti perlu, tempatnya di `EmployeeLeaveService`, bukan di model.

!!! note "`carried_over` masih kolom kosong"
    Kolomnya ada di model dan di schema UI, tapi **tidak ada satu baris kode pun yang menulisnya** — sama untuk `allow_carry_over`, `carry_over_max_days`, dan `carry_over_expiry_months` di policy. Sisa cuti tahun lalu hari ini bukan hangus pada 1 Januari; ia tidak pernah ada.

    Rancangannya — bawaan, masa berlaku, arsip yang hangus, cuti dibayar di muka, dan penyelesaian saat resign/PHK — ada di **[Proposal: Saldo Cuti](Leave-Balance-Proposal.md)**.

---

## `LeavePolicy` — aturannya, bukan angkanya

```bash
tenant_command seed_leave_policy                        # hanya ANNUAL-STD
tenant_command generate_leave_balances --year=2027      # --dry-run tersedia
```

- Berjenjang lewat skor `specificity`; **kosong = berlaku untuk semua**
- **`adjustment` tidak pernah disentuh generator** — itu yang membuat perhitungan ulang aman dijalankan kapan saja
- **Nol selalu punya alasan yang bisa dibaca** (`Entitlement.reason`) — saldo nol tanpa penjelasan adalah keluhan yang paling sering sampai ke HR
- Jenis cuti **tanpa policy tidak menghasilkan baris saldo sama sekali**; cutinya tetap bisa dicatat, cuma tidak ada angka yang dipotong

!!! danger "Jangan seed jatah untuk jenis cuti yang tidak punya dasar"
    `SICK-STD` sempat diseed 30 hari dan angka itu **karangan** — UU tidak mengatur kuota hari sakit per tahun, melainkan skala upah selama sakit berkepanjangan.

    Angka karangan di master lebih berbahaya daripada tidak ada angka. Sudah ditarik lewat `OBSOLETE_CODES`.

Saldo juga terbit sendiri saat Join Date diisi (`EmploymentService.sync_leave_balances`).

---

## Nomor dokumen

Deret `hr/leave` (prefix `LV`), diberikan saat record **dibuat** untuk semua jalur, tidak pernah dihitung ulang.

Deret yang belum diseed → nomor kosong, **record tetap tersimpan**. Cuti tidak boleh gagal dicatat gara-gara master penomoran belum diisi.

---

## Tumpang tindih

Dicek **lintas jenis cuti** — orang tidak bisa cuti tahunan sekaligus sakit di hari yang sama.

Tiga lapis dengan perilaku **sengaja berbeda**: menolak saat create/update, menolak saat Submit TR, dan **tidak melempar** saat penerbitan. Detail: [Overview](../../09-business-flows/Overview.md#cuti-tumpang-tindih-dua-pintu-satu-penjagaan).

---

## Yang belum ada

- **Eksekusi carry-over** — kolomnya sudah ada di `LeavePolicy`
- Pembatasan pemakaian per bulan berjalan untuk akrual bulanan
- **`schema.actions` belum digenerate FE** untuk modul Leave — endpointnya jalan, tombolnya belum muncul. Perlu `pnpm meinova generate hr/leave`
- Cuti besar, melahirkan, dan haid belum punya policy — **sengaja**, sampai aturan perusahaannya jelas
