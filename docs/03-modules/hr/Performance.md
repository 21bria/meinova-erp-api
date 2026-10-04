# Performance

❌ **Belum ada.** `apps/hr/models/performance.py` adalah **file kosong, 0 baris**.

---

## Yang sudah ada: masternya saja

Sembilan master referensi sudah diseed dan punya layarnya, tapi **belum ada satu pun model transaksi yang memakainya**:

| Master | `framework_module` |
|---|---|
| KPI Category | `references/hr/kpi-categories` |
| KPI Period | `references/hr/kpi-periods` |
| KPI Weight Type | `references/hr/kpi-weight-types` |
| Performance Rating | `references/hr/performance-ratings` |
| Performance Cycle | `references/hr/performance-cycles` |
| Performance Template | `references/hr/performance-templates` |
| Competency Category | `references/hr/competency-categories` |
| Competency | `references/hr/competencies` |
| Competency Level | `references/hr/competency-levels` |

Master ini bagian dari seed `hr-reference`, jadi ia ada di setiap tenant.

!!! warning "Master yang ada tanpa transaksi yang memakainya"
    Layarnya bisa dibuka dan datanya bisa diisi, tapi tidak berpengaruh ke apa pun. Kalau ada yang mengisinya, ia akan mengira modulnya sudah jalan.

---

## Konsekuensi yang sudah terlihat

Kartu **"Kinerja Tercapai"** dari mockup dashboard HR **sengaja tidak dibuat**.

Prinsip yang berlaku di seluruh sistem ini:

> **Widget yang datanya belum ada modelnya tidak dibuat, bukan diisi angka contoh.**

Tempatnya diisi **Jam Lembur** dan **Lowongan Terbuka** yang datanya nyata. Alasan yang sama membuat "Monthly Payroll" dan "Revenue vs Expense" hilang dari beranda.

---

## Kalau nanti dibangun

Beberapa hal yang sudah jelas dari struktur yang ada — supaya tidak dirancang dari nol:

### Ikuti pola dokumen berapproval yang sudah ada

Penilaian kinerja adalah dokumen: punya status, punya pengaju, punya beberapa meja (pegawai → atasan → HR). Engine-nya sudah ada dan generik.

Checklistnya di [Build A Module](../../02-Framework/Build-A-Module.md#kalau-modulnya-dokumen-berapproval).

### Aturan siapa menilai siapa: master, bukan izin model

Django Permission cuma tahu `add_performancereview` — ia tidak bisa membedakan "atasan menilai bawahannya" dari "HR menilai siapa saja".

Pola yang sudah terbukti untuk masalah ini: **`EmployeeActionPolicy`** (siapa boleh mengusulkan) dan **`EmployeeDataPolicy`** (siapa boleh melihat). Keduanya berjenjang lewat skor `specificity` dan bisa diubah dari layar tanpa rilis kode.

### Hasil penilaian itu data sensitif

Kalau dibuat, ia layak masuk `EmployeeDataPolicy` sebagai kelompok tersendiri — dan **wajib** ditutup di tiga jalur (serializer, endpoint sub-resource, export CSV).

Catatan yang sudah ada: `EDP-MEDICAL` sengaja **tanpa atasan**, karena kondisi kesehatan bukan bahan penilaian kinerja. Kebalikannya berlaku di sini — hasil penilaian memang urusan atasan, tapi belum tentu urusan rekan setingkat.

### Siklus penilaian cocok dengan Celery Beat yang sudah jalan

`hr.dispatch_employee_reminders` sudah berjalan tiap jam 6 pagi dan menyebar per schema. Pengingat "periode penilaian dibuka" tinggal meniru polanya — tidak perlu penjadwal baru.

### Jangan seed angka bobot karangan

Pelajaran dari `SICK-STD` yang diseed 30 hari tanpa dasar: **angka karangan di master lebih berbahaya daripada tidak ada angka**, karena orang menganggapnya sudah divalidasi.

Bobot KPI dan skala rating harus datang dari kebijakan perusahaan, bukan dari nilai bawaan yang kelihatan masuk akal.

---

## Terkait

`apps/hr/models/separation.py` juga **file kosong**. Turnover di dashboard dihitung dari `EmploymentAssignment.termination_date`, dan pengunduran diri/terminasi ditangani sebagai jenis `EmployeeAction` — bukan modul tersendiri.

Itu pilihan yang masuk akal dan mungkin tidak perlu diubah.
