# Logging

!!! danger "Belum dikonfigurasi sama sekali"
    `config/settings/logging.py` **kosong**, dan tidak ada `LOGGING` di `base.py`.

    Ini bukan kekurangan kenyamanan. Beberapa jalur di sistem ini **sengaja menelan exception dan hanya mencatat log** — tanpa logging terkonfigurasi, kegagalannya hilang total.

Prosedur dan konfigurasi minimum ada di **[Monitoring](../07-deployment/Monitoring.md)**. Halaman ini menjelaskan **kenapa** desainnya menuntut logging.

---

## Pola "gagal berisik" vs "gagal ke log"

Sistem ini memilih dengan sengaja mana yang boleh menggagalkan operasi dan mana yang tidak.

### Yang menggagalkan (melempar)

| Kasus | Kenapa |
|---|---|
| Approver tidak ketemu saat submit | dokumen yang berjalan dengan satu kotak kosong akan mengendap tanpa ada yang merasa ditagih |
| Widget dashboard tanpa resolver | `NotImplementedError` — sengaja berisik daripada tampil kosong |
| `full_clean()` gagal | 400 berisi error per field |

### Yang TIDAK menggagalkan — hanya `logger`

Dan di sinilah logging jadi wajib:

| Jalur | Yang ditelan | Kalau tidak terpantau |
|---|---|---|
| `BaseService._audit` | kegagalan pencatatan audit | perubahan tercatat, jejaknya tidak — dan tidak ada yang tahu jejaknya bolong |
| `EmploymentService.sync_leave_balances` | kegagalan penerbitan saldo | pegawai baru tanpa saldo cuti, tanpa sebab yang terlihat |
| `AttendanceEmployeeMatcher.names_match` | nama tidak cocok saat sync | **nomor salah enroll menempel ke karyawan lain** — pernah terjadi di produksi, 1.326 tap |
| `SafeSearchFilter` | field pencarian tak dikenal | pencarian diam-diam tidak mencari yang diharapkan |
| `WorkflowStep.condition` tak bisa dinilai | | step approval berjalan padahal seharusnya dilewati |
| `issue_leave_records` bentrokan beda jenis | | catatan cuti tidak terbit dari TR yang disetujui |
| `@register_completion` didaftarkan dua kali | | handler belakangan menang, diam-diam |

**Baris ketiga yang paling mahal.** Verifikasi nama sengaja jadi **alarm, bukan gerbang** — absensi tidak boleh hilang gara-gara ejaan nama.

Tapi alarm yang tidak ada yang mendengarnya sama saja dengan tidak ada alarm.

---

## Kenapa `_audit` memakai savepoint sendiri

```python
with transaction.atomic():      # savepoint
    AuditTrail.objects.create(...)
```

Bukan sekadar kerapian:

!!! warning "Tanpa savepoint, exception di dalam transaksi induk membuat seluruh transaksinya tidak bisa di-commit lagi — MESKI exception-nya ditangkap"
    Jadi kegagalan mencatat audit akan membatalkan perubahan bisnisnya. Savepoint yang mencegahnya.

Pola yang sama berlaku untuk webhook kalau nanti dibuat.

---

## Yang perlu ada di log

Dua hal yang khas sistem ini:

### 1 · Schema tenant

"Ada error jam 9" tidak memberi tahu **klien mana**. Untuk multi-tenant, `connection.schema_name` wajib ikut di setiap baris log.

### 2 · Request ID

`apps/core/middleware/request_id.py` masih **file kosong** dan tidak terdaftar di `MIDDLEWARE`.

Tanpa itu, tidak ada cara mengaitkan error yang dilihat pengguna di layar dengan baris log di server.

---

## Middleware yang masih kosong

`apps/core/middleware/`:

| Berkas | Keadaan |
|---|---|
| `current_user.py` | ✅ **jalan** — `CurrentRequestMiddleware` |
| `audit.py` | kosong |
| `request_id.py` | kosong |
| `timezone.py` | kosong |
| `exception.py` | kosong |

`CurrentRequestMiddleware` memakai **`contextvars`, bukan `threading.local`** — yang kedua bocor antar-request di server async, dan **nilai milik pengguna lain yang tercatat sebagai milik sendiri justru kesalahan paling berbahaya di jejak audit**.

Ia sengaja **hanya untuk data pelengkap** (IP, user agent). Otorisasi dan `created_by` tetap mengoper `user=` eksplisit — kalau tidak, pemanggil non-HTTP (management command, task Celery, test) berperilaku berbeda dari jalur API **tanpa satu pun tanda di kodenya**.

---

## Audit trail bukan pengganti log

`AuditTrail` mencatat **siapa mengubah apa**. Batasnya:

- **Viewset tanpa `ServiceWriteMixin` tidak masuk audit sama sekali**
- **Yang tanpa pengguna terautentikasi tidak dicatat** — seed, importer, command
- **Login/logout tidak dicatat** (bukan mutasi model)
- Membaca tidak dicatat sama sekali

Jadi **"tidak ada di audit trail" bukan bukti sesuatu tidak terjadi.**

---

## Langkah berikutnya

1. Isi `config/settings/logging.py` — konfigurasi minimumnya ada di [Monitoring](../07-deployment/Monitoring.md)
2. `from .logging import *` di `base.py`
3. Pastikan logger `apps` **tidak tersaring**
4. Tambahkan schema tenant + request ID
5. Error tracking (Sentry)
