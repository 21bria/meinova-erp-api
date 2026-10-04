# Medical

🟡 **Sebagian.** Ada modelnya sebagai sub-data pegawai, belum ada modul tersendiri.

---

## Yang ada

`EmployeeMedicalEvent` (`apps/hr/models/employee_medical_event.py`) — sub-data di kartu pegawai, tab **Medical**.

Endpoint: `/api/hr/employee-medical-events/`.

Master pendukung yang sudah diseed: `blood-types`.

---

## Kerahasiaan: sudah ditutup

`EmployeeDataPolicy` bawaan memuat **`EDP-MEDICAL`**, dan konfigurasinya sengaja berbeda dari yang lain:

| Policy | Yang boleh melihat |
|---|---|
| `EDP-PAYROLL` | yang bersangkutan, **atasan langsung**, HR-MANAGER |
| `EDP-BANK` | yang bersangkutan, HR-MANAGER — **tanpa atasan** |
| `EDP-MEDICAL` | yang bersangkutan, HR-MANAGER — **tanpa atasan** |

!!! note "Kenapa atasan langsung dikecualikan"
    **Kondisi kesehatan bukan bahan penilaian kinerja.** Dan nomor rekening dipakai untuk membayar orang, bukan untuk dibaca atasannya.

    Ini keputusan yang layak dipertahankan kalau modul medical nanti dikembangkan.

Penutupannya berlaku di **tiga jalur** — serializer, endpoint sub-resource (`EmployeeDataSubjectMixin` di `filter_queryset()`), dan export CSV. Menutup satu tidak menutup dua lainnya.

---

## Yang belum ada

| | Catatan |
|---|---|
| **Modul tersendiri** | tidak ada `framework_module` untuk medical; hanya sub-data |
| **MCU (Medical Check-Up) terjadwal** | relevan untuk pegawai tambang — MCU berkala biasanya syarat masuk site |
| **Kaitan ke kelayakan kerja** | tidak ada penanda "fit to work" yang memblokir penjadwalan roster |
| **Kaitan ke cuti sakit** | `EmployeeMedicalEvent` dan `EmployeeLeave` bertipe sakit tidak saling menunjuk |
| **Master penyakit / diagnosis** | |
| **Lampiran hasil pemeriksaan** | `apps/uploads` ada, belum disambungkan |

---

## Kalau nanti dikembangkan

Beberapa hal yang sudah jelas dari struktur yang ada:

1. **Ikuti `EDP-MEDICAL` yang sudah ada** — jangan buat mekanisme kerahasiaan baru. Kelompok `field_*` dan `history_*` di `EmployeeDataPolicy` sudah jadi tempatnya.
2. **MCU berkala cocok dengan `hr.dispatch_employee_reminders`** yang sudah jalan tiap jam 6 pagi — polanya tinggal ditiru, tidak perlu penjadwal baru.
3. **"Fit to work" yang memblokir roster adalah keputusan besar.** Kalau dibuat, ia harus jadi **peringatan di `preview()`**, bukan penolakan di `commit/` — pola yang sama dengan pasangan back-to-back. Jadwal yang tidak bisa diterbitkan karena satu MCU kedaluwarsa akan lebih merusak daripada menolongnya.
4. **Data medis di export CSV harus dibuang seluruh kolomnya**, bukan dikosongkan per baris — CSV yang sebagian selnya terisi membocorkan polanya.
