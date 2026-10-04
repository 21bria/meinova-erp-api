# Vision

**ERP multi-tenant untuk perusahaan Indonesia, dengan HR operasional lapangan sebagai fondasinya.**

---

## Masalah yang diselesaikan

Sistem ini lahir dari kebutuhan klien tambang, dan itu terlihat di seluruh desainnya.

Pegawai tambang bekerja dalam **siklus**: sekian minggu di site, sekian minggu field break, dengan hari perjalanan di antaranya. ERP umum tidak mengenal pola ini — mereka mengasumsikan Senin–Jumat, satu lokasi, dan cuti yang dihitung dari kalender.

Akibatnya di lapangan:

- Jadwal roster disusun di Excel, dan tidak ada yang tahu versi mana yang berlaku
- Travel Request ditulis tangan, disetujui lewat WhatsApp, tiketnya dibeli sebelum KTT setuju
- Cuti pegawai site dihitung dengan aturan pegawai kantor, dan angkanya salah
- Absensi mesin fingerprint ditarik manual, dan nomor yang salah enroll menempel ke orang lain tanpa ada yang tahu

Keempatnya sudah ditangani. Yang keempat pernah terjadi sungguhan: 1.326 tap masuk ke kartu orang yang salah.

---

## Yang membedakannya

### 1 · Satu struktur untuk UMKM sampai tambang multi-lokasi

Hierarki organisasinya lengkap — Company → Branch → Location → Division → Department → Section — tapi **hanya Company yang wajib**. Semua level lain nullable dan boleh dilompati.

Konsekuensinya: klien satu kantor tidak perlu mengisi enam level kosong, dan klien dua belas perusahaan lintas pulau tetap terwadahi. Tanpa dua produk.

### 2 · Backend adalah sumber kebenaran untuk UI

Form dan tabel tidak ditulis tangan — digenerate dari schema yang dideklarasikan di backend.

Artinya menambah modul berarti menulis model, service, dan schema. Layarnya menyusul otomatis. Dan perbaikan di lapisan framework **langsung berlaku di seratus modul tanpa satu pun disunting**.

### 3 · Aturan sebagai data, bukan sebagai kode

Lima master aturan (`WorkflowDefinition`, `LeavePolicy`, `RosterPolicy`, `EmployeeActionPolicy`, `EmployeeDataPolicy`) menentukan hal-hal yang di sistem lain tertanam di kode: siapa menyetujui dokumen siapa, berapa jatah cuti, siapa boleh mengusulkan kenaikan gaji, siapa boleh melihat riwayat gaji.

Semuanya diatur dari layar, per tenant, **tanpa rilis kode**.

### 4 · Deployment fleksibel dari satu codebase

Shared multi-tenant untuk klien SMB, dedicated/on-premise untuk enterprise — **kode yang sama**. Isolasi datanya properti database (schema-per-tenant), bukan kolom `tenant_id` yang harus diingat difilter.

---

## Prinsip yang membentuk keputusan sehari-hari

Enam hal yang muncul lagi dan lagi. Semuanya bisa ditunjuk ke kode.

### Yang datanya belum ada tidak dibuat, bukan diisi angka contoh

Widget "Monthly Payroll Rp 1.2B" dan "Active Employees 248" pernah muncul di tenant berisi 10 orang — angka yang sama persis untuk setiap orang yang login, **termasuk saat didemokan ke klien**.

Semuanya dihapus, bukan diganti nol. Angka karangan di layar adalah utang yang dibayar pelanggan.

Berlaku juga di master: `SICK-STD` 30 hari pernah diseed dan angka itu tidak punya dasar hukum. **Angka karangan lebih berbahaya daripada tidak ada angka**, karena orang menganggapnya sudah divalidasi.

### Gagal berisik lebih baik daripada gagal diam

Widget tanpa resolver melempar. Approver yang tidak ketemu menggagalkan seluruh pengajuan.

Kebalikannya juga disengaja: hal yang **tidak boleh** memblokir tetap dicatat sebagai peringatan — nama tidak cocok saat sync absensi, celah antar periode roster.

### Kosong berarti "berlaku untuk semua"

Di seluruh master aturan. **Role tanpa satu pun baris cakupan = tanpa batasan**, bukan tanpa akses.

### Riwayat disimpan, tidak ditimpa

`EmployeeAction` terpisah dari `EmploymentAssignment`. `PayrollAssignment` effective-dated. `RotationPeriod` berversi. Ledger kredit append-only.

Karena pertanyaan "sejak kapan saya permanen" dan "dari mana ke mana" harus bisa dijawab.

### Delete selalu soft delete

Tidak ada endpoint hapus permanen. Satu-satunya pengecualian: byte file upload, karena ia benar-benar memakan disk.

### Menu tersembunyi bukan penjagaan

Yang menolak sungguhan selalu API. Tiga lapis yang berbeda pertanyaannya: boleh mengubah tabel ini, menu ini disodorkan atau tidak, **baris yang mana** yang boleh dilihat.

---

## Yang sudah nyata hari ini

| | Status |
|---|---|
| `core`, `framework` | ✅ fondasi schema-driven |
| `accounts` | ✅ RBAC tiga lapis |
| `administration` | ✅ organisasi, master, kalender, audit, dashboard |
| `hr` | ✅ modul terlengkap — 24 module, 37 migrasi |
| `workflow` | ✅ engine approval generik |
| `imports`, `uploads` | ✅ |
| `payroll` | 🟡 master lengkap, belum ada payroll run |
| `assets`, `finance`, `reports`, `scm` | 📋 stub kosong |

Detail: [Module Registry](../03-modules/Module-Registry.md).

---

## Arah berikutnya

Bukan daftar fitur — tiga hal yang paling menentukan:

1. **Payroll run.** Satu-satunya modul yang masternya lengkap tapi intinya belum ada.
2. **Kesiapan produksi.** `production.py` praktis kosong, logging belum dikonfigurasi, belum ada backup terjadwal. Lihat [Production](../07-deployment/Production.md).
3. **Cakupan test.** Test hanya ada di `apps/hr/`. `workflow` — yang paling banyak aturannya — belum punya satu pun.

Ketiganya lebih penting daripada modul baru.

---

## Yang sengaja TIDAK dikerjakan

| | Kenapa |
|---|---|
| Versioning API | frontend digenerate dari backend dan dirilis bersamaan; versioning cuma menambah dimensi yang harus dijaga sinkron |
| Memisah form cuti HO vs site | yang berbeda cara menghitungnya, bukan jenis cutinya |
| Drag untuk menyusun widget | di ponsel bertabrakan dengan gulir halaman |
| Ukuran widget bebas | tiap widget harus terlihat benar di berapa pun lebar; biayanya jauh lebih besar daripada nilainya |
| Menyimpan bawaan ke DB | pembeda "belum pernah menyusun" adalah **tidak adanya baris** |
