# Testing

Keadaan sebenarnya: **test hanya ada di dua tempat.** Sisanya `tests.py` kosong.

```
apps/hr/tests/roster/     ← 4 berkas
apps/hr/tests/policy/     ← pemetaan EmployeeDataPolicy
```

Halaman ini menjelaskan cara menjalankannya, dan **pola yang harus diikuti** kalau kamu menambah test — karena django-tenants membuat beberapa asumsi Django biasa tidak berlaku.

---

## Menjalankan

```bash
python manage.py test apps.hr.tests.roster --keepdb
python manage.py test apps.hr.tests.policy          # tidak butuh DB
python manage.py test                                # semuanya
```

!!! danger "`--keepdb` bukan opsional"
    Tiap `TenantTestCase` membuat schema tenant sendiri lewat `migrate_schemas`. Tanpa `--keepdb`, sekali jalan **~4 menit**.

---

## Dua jenis test, dan pembagiannya disengaja

| Berkas | Base class | Sentuh DB? |
|---|---|---|
| `test_rotation_generator.py` | `SimpleTestCase` | **tidak** |
| `test_roster_calculation.py` | `SimpleTestCase` | **tidak** |
| `apps/hr/tests/policy/` | `SimpleTestCase` | **tidak** |
| `test_leave_day_calculator.py` | `TenantTestCase` | ya |
| `test_roster_flow.py` | `TenantTestCase` | ya |

`RosterCalculationService` dan `RotationPeriodGenerator` memang **fungsi murni tanpa satu pun query**, dan itu properti yang harus tetap dijaga:

> Begitu ada yang menambahkan query ke kalkulator, dua berkas `SimpleTestCase` itu yang **pertama gagal**. Itu memang gunanya.

Karena itu perhitungan roster dipisahkan dari pengambilan datanya sejak awal — preview, penulisan, dan perhitungan ulang memakai jalan yang sama dan bisa diuji tanpa menyiapkan tenant.

---

## `TenantTestCase` berperilaku berbeda dari `TestCase`

!!! danger "Tidak ada rollback per-test"
    `TenantTestCase` django-tenants **tidak memanggil `super().setUpClass()`**. Akibatnya:

    - **Tidak ada rollback transaksi antar test** — data yang dibuat test pertama masih ada di test kedua
    - **`setUpTestData` tidak jalan**

    Konsekuensi praktisnya: **tiap test wajib membuat pegawainya sendiri dan hanya membaca miliknya.** Test yang berasumsi tabelnya kosong akan lolos sendirian lalu gagal saat dijalankan bersama yang lain.

```python
class RosterFlowTest(TenantTestCase):
    def test_commit_creates_baseline(self):
        employee = self._make_employee("TEST-A-001")   # miliknya sendiri
        ...
```

Gunakan awalan nomor pegawai yang unik per test, jangan `EMP001`.

---

## Apa yang layak dites lebih dulu

Codebase ini punya banyak aturan yang **gagal tanpa suara**. Itu tepat kelas masalah yang paling murah ditutup test dan paling mahal ditemukan di produksi.

Prioritas, dari yang paling berharga:

| Prioritas | Contoh nyata |
|---|---|
| **Kalkulator murni** | matematika siklus roster, hari cuti, konversi kredit — sudah ada |
| **Pemetaan yang wajib lengkap** | `SUBJECT_ACTION_TYPES` di `EmployeeDataPolicy`: jenis yang tidak masuk kelompok mana pun **tidak bisa dibatasi sama sekali**, dan kelalaian itu tidak berbunyi — sudah ada |
| **Idempotensi** | `apply()` dipanggil dua kali tidak boleh menerapkan dua kali; `commit/` yang diulang melewati baris `COMMITTED` |
| **Penjagaan izin** | PATCH `is_superuser: true` ke `/auth/me` harus dibalas 200 **tanpa** mengubah kolomnya |
| **Cakupan data** | admin site membaca 6 pegawai, bukan 10 |
| **Efek samping** | approve TR menerbitkan catatan cuti; approve ulang tidak memotong dua kali |

Contoh yang sudah terbukti berguna: `test_cycle_advance_counts_travel_once` — menangkap kesalahan `work + off + travel * 2` yang membuat tanggal mulai meleset dan **melesetnya menumpuk sepanjang tahun**.

Dan `RosterPolicyResolver.travel_days_for()` yang tidak dioper `policy=` ketahuan **lewat test, bukan lewat layar** — jadwalnya tetap terbit, cuma tanpa satu pun segmen travel.

---

## Menulis test yang butuh tenant

```python
from django_tenants.test.cases import TenantTestCase


class LeaveDayCalculatorTest(TenantTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()      # WAJIB — TenantTestCase butuh ini
        # seed master minimal yang diperlukan test ini saja

    def test_ho_employee_excludes_weekend(self):
        ...
```

Seed **hanya** master yang dibutuhkan test itu. Memanggil `seed_administration` penuh di `setUpClass` membuat suite-nya lambat dan mengikat test pada isi seed yang bisa berubah.

---

## Yang belum ada

| | Catatan |
|---|---|
| **Test di app selain `hr`** | `accounts`, `administration`, `workflow`, `framework` semuanya `tests.py` kosong — padahal `workflow` justru yang paling banyak aturannya |
| **Test API level HTTP** | Tidak ada satu pun yang menembak endpoint lewat `APIClient`. Seluruh penjagaan permission diverifikasi manual |
| **Test frontend** | Tidak ada |
| **CI** | Tidak ada `.github/`. Test dijalankan manual |
| **Coverage** | Tidak diukur |
| **Factory / fixture bersama** | Tiap test merakit datanya sendiri dari nol |

!!! note "Prioritas kalau mau menambah, berurutan"
    1. **`workflow`** — resolver approver punya lima tipe, cakupan berjenjang, cadangan bertingkat, dan kondisi step. Semuanya bisa dites tanpa HTTP.
    2. **Penjagaan permission lewat `APIClient`** — tiga lapis yang saling mudah tertukar.
    3. **CI** yang menjalankan `python manage.py test --keepdb` di setiap push.

---

## Verifikasi manual yang tidak bisa digantikan test

Beberapa hal di sistem ini **hanya** ketahuan di browser sungguhan:

- `<SelectItem value="">` melempar saat **hidrasi**, bukan SSR — `curl` membalas 200 dan `nuxi build` lolos walau halamannya rusak
- Kolom "-" di semua baris (key `columns.ts` tidak ada di payload)
- Prop hantu yang jatuh jadi atribut mati — Vue tidak mengeluhkan prop tak dikenal
- Rute baru yang 404 sampai dev server direstart

Karena itu checklist rilis menyebut **"buka halamannya di browser"** sebagai langkah tersendiri, bukan basa-basi.
