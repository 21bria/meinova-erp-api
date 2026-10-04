# Training

`framework_module = "hr/training"` dan `"hr/training-participants"`.

---

## Dua model yang jangan tertukar

| Model | Isi |
|---|---|
| **`TrainingProgram`** | batch penyelenggaraan — satu pelatihan yang dijadwalkan, punya kuota dan peserta |
| **`EmployeeTraining`** | riwayat pelatihan **milik satu pegawai**, termasuk yang diikuti **sebelum bergabung** |

Penghubungnya `TrainingParticipant.employee_training`.

!!! note "Kenapa dipisah"
    Riwayat pelatihan seseorang tidak selalu berasal dari program internal. Sertifikat K3 yang dibawa dari perusahaan sebelumnya tetap harus tercatat, dan ia tidak punya batch penyelenggaraan di sistem ini.

`EmployeeTraining` tampil sebagai sub-data di kartu pegawai; `TrainingProgram` punya modulnya sendiri.

---

## Status

| Model | Choices |
|---|---|
| `TrainingProgram` | `TrainingProgramStatus` |
| `TrainingParticipant` | `ParticipantStatus` |

Belum disambungkan ke engine approval — pendaftaran peserta tidak melewati alur persetujuan.

---

## Kuota ditegakkan di service, bukan `Model.clean()`

```python
quota = models.PositiveSmallIntegerField(null=True, blank=True)
```

`Model.clean()` hanya memeriksa `quota > 0` — konsistensi satu record.

**Jumlah peserta terhadap kuota diperiksa di service**, karena aturannya menyangkut **jumlah baris lain**. Itu aturan pembagi yang berlaku di seluruh codebase ini.

!!! note "Program tanpa kuota = tanpa batas"
    `quota = None` sah. Induksi K3 yang wajib diikuti seluruh site tidak punya angka batas.

---

## Cakupan data

`TRAINING_SCOPE` dipanggil dengan **`allow_null=True`**:

> Di `TrainingProgram`, kolom company yang kosong berarti **"berlaku untuk semua"**, bukan "belum diisi". Program induksi K3 se-grup tidak boleh hilang dari layar admin site.

!!! danger "Jangan pakai `allow_null=True` sebagai jalan pintas"
    Ia hanya benar untuk model yang kosongnya **memang bermakna**. Untuk model yang kosongnya cuma karena datanya belum lengkap, ia membuka data yang seharusnya tertutup.

Petanya ada di `apps/hr/api/dashboard/services.py` dan **disamakan persis** dengan `data_scope` di viewsetnya — kalau salah satu diubah, yang satunya harus ikut, kalau tidak angka dashboard tidak cocok dengan isi tabelnya.

---

## Master

`references/hr/training-category` dan `references/hr/training-provider`, plus `certificate-types` dan `competencies` untuk hasil pelatihannya.

Diseed lewat `seed_administration --only=hr-reference`.

---

## Yang belum ada

- **Approval pendaftaran peserta** — statusnya ada, engine-nya belum disambungkan
- **Pengingat sertifikat kedaluwarsa** — `EmployeeCertificate` punya tanggal berlakunya, dan `hr.dispatch_employee_reminders` sudah jalan tiap pagi; tinggal ditambahkan ke pengingat yang ada
- **Kaitan ke matriks kompetensi** — `Competency`, `CompetencyLevel`, `CompetencyCategory` sudah ada sebagai master tapi belum dipakai untuk menilai kesenjangan pelatihan
- Biaya pelatihan & anggaran
