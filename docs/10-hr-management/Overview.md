# HR Management — Overview

Dokumen ini menjelaskan **bagaimana seorang pegawai bergerak melalui sistem**, dari struktur organisasi sampai buku besar. Ditulis untuk manajemen, HR, payroll, finance, dan atasan langsung — bukan untuk membaca kode.

!!! abstract "Status dokumen"
    Halaman-halaman di bagian ini tumbuh bertahap. Yang sudah berisi fakta terverifikasi ditandai **IMPLEMENTED**; yang baru berlaku untuk data peragaan ditandai **CONFIGURED FOR DEMO**; batas yang diketahui ditandai **KNOWN LIMITATION**; yang belum ada ditandai **FUTURE / NOT IMPLEMENTED**. Tidak ada capability yang dijelaskan di sini tanpa bukti dari sistem yang berjalan.

---

## Perjalanan satu pegawai

```mermaid
flowchart TD
    ORG["Organization<br/>Company · Location · Department"] --> EMP["Employee<br/>identitas"]
    EMP --> EMPL["Employment<br/>status, golongan, kontrak"]
    EMPL --> OA["Organization Assignment<br/>penempatan"]
    OA --> WL["Work Location<br/>Head Office atau Site"]
    WL --> SCH{"Pola kerjanya?"}
    SCH -->|Kantor| WC["Work Calendar<br/>hari kerja mingguan"]
    SCH -->|Site| RO["Roster<br/>siklus kerja & field break"]
    WC --> SH["Shift<br/>jam kerja"]
    RO --> SH
    SH --> PWD["Planned Work Day<br/>hari + jam yang dijadwalkan"]
    PWD --> EV["Attendance Evidence<br/>tap mesin / import / input"]
    EV --> CA["Attendance Calculation<br/>Attendance Policy"]
    CA --> ST["Attendance Status<br/>Present · Late · Absent"]
    PWD -. "tidak ada bukti" .-> CL["Attendance Closing"]
    CL --> ST
    ST --> PF["Payroll Period Facts"]

    ST --> LV["Leave"]
    ST --> PM["Permission"]
    ST --> OT["Overtime"]
    LV --> PF
    PM --> PF
    OT --> PF

    L5["Payroll"]:::later -. "HR-DEMO-5" .-> PF
    L6["Finance"]:::later -. "HR-DEMO-6" .-> L5

    classDef later fill:#e5e7eb,color:#374151,stroke-dasharray: 5 5

    style ORG fill:#1e40af,color:#fff
    style WL fill:#7c2d12,color:#fff
    style PWD fill:#166534,color:#fff
    style ST fill:#166534,color:#fff
    style PF fill:#92400e,color:#fff
```

Sampai **Planned Work Day**, sistem belum tahu apa pun tentang kehadiran. Ia baru tahu **kapan orang ini seharusnya bekerja dan jam berapa**. Semua yang datang sesudahnya — presensi, cuti, izin, lembur, payroll, jurnal — mengukur dirinya terhadap jadwal itu.

Tiga cabang sesudah presensi adalah **penjelasan atas pengecualian**, bukan bagian dari perhitungan kehadirannya: Cuti menerangkan hari yang tidak dijalani, Izin Kehadiran menerangkan menit yang menyimpang, Lembur mengakui jam di luar jadwal. Ketiganya bermuara di fakta yang sama yang dibaca Payroll.

Yang digambar putus-putus **belum tersambung**: Payroll dan Finance menyusul di fasenya masing-masing.

Itu sebabnya bagian ini dibangun lebih dulu: angka kehadiran yang benar mustahil ada di atas jadwal yang salah.

---

## Peta keseluruhan

Rantai penuh yang akan dijelaskan bertahap di bagian ini:

```mermaid
flowchart LR
    A["Organization<br/>& Employee"] --> B["Calendar · Roster · Shift"]
    B --> C["Attendance"]
    C --> D["Leave · Permission · Overtime"]
    D --> E["Payroll"]
    E --> F["Accounting Event"]
    F --> G["Journal"]
    G --> H["General Ledger"]

    style A fill:#1e40af,color:#fff
    style C fill:#166534,color:#fff
    style E fill:#92400e,color:#fff
    style H fill:#581c87,color:#fff
```

| Tahap | Halaman | Status |
|---|---|---|
| Organisasi & penempatan | [Organization Management](Organization.md), [Head Office vs Site](HO-vs-Site.md) | **IMPLEMENTED** |
| Kalender, shift, roster | [Work Calendar](Work-Calendar.md), [Shift](Shift.md), [Roster](Roster.md) | **IMPLEMENTED** |
| Aturan yang mengatur semuanya | [Policy Resolution](Policy-Resolution.md) | **IMPLEMENTED** |
| Siapa boleh apa | [Roles & Data Scope](Roles-And-Data-Scope.md) | **IMPLEMENTED** |
| Presensi | [Attendance](Attendance.md), [Aturan & Perhitungan](Attendance-Rules.md), [Penutupan & Batas Modul](Attendance-Closing.md), [Contoh Manajemen](Attendance-Examples.md) | **IMPLEMENTED** |
| Cuti, izin, lembur | [Leave](Leave.md), [Permission](Permission.md), [Overtime](Overtime.md) | **IMPLEMENTED** — persetujuan lembur **FUTURE** |
| Visitor | — | menyusul |
| Payroll | — | menyusul |
| Payroll → Finance | — | menyusul |

---

## Prinsip yang berlaku di seluruh modul

**Aturan bisnis tidak ditanam di kode.** Jam masuk, toleransi keterlambatan, pola roster, jatah cuti, ambang lembur, hari libur — semuanya master data yang bisa diubah HR tanpa menunggu rilis. Kalau sebuah angka tidak bisa diubah dari layar, itu dicatat sebagai keterbatasan, bukan disembunyikan.

**Ketidakhadiran bukan sebuah baris — ia baris yang tidak ada.** Mesin presensi hanya mengirim tap. Orang yang tidak masuk tidak menghasilkan apa pun. Sistem yang menyimpulkan "tidak hadir" dari jadwal yang kosong, bukan seed yang menuliskannya.

**Jam tap adalah fakta dan tidak pernah diubah aturan.** Toleransi memengaruhi status dan menit keterlambatan; jam masuk yang tersimpan tetap jam masuk yang sebenarnya.

**Dokumen yang sudah diposting tidak disunting.** Koreksi berjalan lewat dokumen baru atau pembalikan, tidak pernah dengan mengubah yang lama.
