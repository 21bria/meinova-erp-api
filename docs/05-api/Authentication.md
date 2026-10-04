# Authentication (API)

JWT lewat **SimpleJWT**. Halaman ini soal endpoint dan kontraknya; soal *siapa boleh apa* ada di [Permission](../02-Framework/Permission.md).

---

## Endpoint

| Method | URL | Isi |
|---|---|---|
| `POST` | `/api/accounts/auth/login/` | `{username, password}` → `{access, refresh}` |
| `POST` | `/api/accounts/auth/refresh/` | `{refresh}` → `{access}` |
| `GET` | `/api/accounts/auth/me/` | profil + role + izin + cakupan |
| `PATCH` | `/api/accounts/auth/me/` | **ubah profil sendiri** |
| `POST` | `/api/accounts/auth/logout/` | `{refresh}` → blacklist |
| `POST` | `/api/accounts/auth/change-password/` | |

Header:

```
Authorization: Bearer <access>
```

!!! note "Umur token pakai default SimpleJWT"
    `SIMPLE_JWT` **tidak diset** di settings, jadi berlaku bawaannya: access 5 menit, refresh 1 hari. Kalau nanti perlu diubah, tambahkan blok `SIMPLE_JWT` di `config/settings/base.py`.

Logout mem-blacklist refresh token; kegagalannya **ditelan** (`except: pass`) dan tetap membalas 200 — token yang sudah kedaluwarsa atau sudah di-blacklist tidak boleh membuat logout gagal.

---

## `/auth/me` — kontrak ke frontend

Endpoint ini yang menentukan apa yang bisa ditampilkan frontend. Isinya:

| Key | Isi | Dipakai untuk |
|---|---|---|
| `username`, `first_name`, `last_name`, `email` | identitas | |
| `display_name`, `initials` | **dihitung backend** | avatar & sidebar |
| `is_staff`, `is_superuser` | | |
| `roles` | kode role | |
| `permissions` | `app_label.verb_model`; superuser dapat `["*"]` | `useAccess().can()` |
| `capabilities` | wewenang dari `apps/accounts/capabilities.py` | `isGranted()` |
| `placement` | penempatan organisasi orangnya | **mengisi** form (`$me.placement.*`) |
| `data_scope` | ringkasan + nilai yang disiratkan cakupan | **mengunci** form (`$me.data_scope.*`) |

!!! note "`initials` dihitung backend, bukan frontend"
    "Ambil huruf pertama tiap kata" menghasilkan **satu huruf** untuk username seperti `demo.hrmanager` yang tidak punya spasi.

!!! danger "`groups` sengaja TIDAK dikirim"
    `User` mewarisi `groups` bawaan Django tapi tidak ada satu baris kode pun yang membacanya. Mengirimkannya berarti frontend punya dua sumber peran yang salah satunya selalu kosong.

!!! warning "`placement` dan `data_scope` jangan dicampur"
    HR pusat: ditempatkan di Jakarta, cakupannya seluruh tenant. Form-nya boleh **terisi** Jakarta tapi tidak boleh **terkunci** ke sana.

---

## `PATCH /auth/me` — serializer baca dan tulis berbeda

Ini bukan kerapian, ini keamanan.

| Method | Serializer | Field |
|---|---|---|
| `GET` | `MeSerializer` | termasuk `is_staff`, `is_superuser`, `roles`, `permissions` |
| `PATCH`/`PUT` | `ProfileUpdateSerializer` | **hanya** `first_name`, `last_name`, `email` |

Memakai `MeSerializer` sebagai jalur tulis berarti siapa pun bisa menaikkan dirinya jadi **superuser** lewat satu PATCH ke endpoint profilnya sendiri.

Sudah diuji: PATCH yang menyertakan `is_superuser: true` dibalas **200** dan kolomnya **tidak berubah**.

Tiga keputusan lain di endpoint ini:

- **`username` sengaja tidak ikut** — dipakai untuk login, tercetak di jejak audit, dan dirujuk dokumen yang sudah berjalan.
- **Responsnya memakai bentuk baca**, bukan bentuk tulis. Frontend menyimpan seluruh profil dari respons ini; membalas empat kolom saja akan menghapus role dan izin dari state-nya, dan **sidebar langsung kehilangan menunya tanpa satu pun error**.
- **Email diperiksa case-insensitive di serializer.** `UniqueValidator` bawaan DRF membandingkan persis, jadi `Admin@Meinova.id` lolos lalu jatuh sebagai IntegrityError **500** yang tidak menempel di kolom mana pun.

---

## Tenant ditentukan hostname

```
POST http://demo.localhost:8000/api/accounts/auth/login/
```

Akun hidup **di dalam schema tenant**. Username yang sama di dua tenant adalah dua orang berbeda, dan token dari satu tenant tidak berlaku di tenant lain.

---

## Agent absensi — `X-Agent-Key`

Jalur terpisah, bukan JWT:

```
POST /api/hr/attendance/sync/
X-Agent-Key: <MEINOVA_AGENT_API_KEY>
```

Dicocokkan di `apps/hr/api/attendance_sync/permissions.py`.

!!! warning "Satu key global untuk semua agent & tenant"
    Belum ada revoke per-agent. Tenantnya tetap ditentukan hostname, bukan payload.

    Modelnya `ApiKey` sudah ada (dengan `hashed_key` unik global termasuk yang dicabut), tapi jalur sync belum memakainya.

---

## `ENFORCE_MODEL_PERMISSIONS`

Login berhasil ≠ bisa apa-apa. Kalau `seed_security_roles` belum dijalankan di tenant itu, seluruh sistem **read-only kecuali superuser** — dan gejalanya "semua tombol 403" tanpa petunjuk.

Lihat [Onboarding](../08-development/Onboarding.md#4-seed-berurutan).

---

## Yang belum ada

- **Login, logout, dan kegagalan login tidak masuk jejak audit.** Keduanya bukan mutasi model, jadi tidak lewat service mana pun. Tempatnya nanti signal `user_logged_in` / `user_login_failed`, **bukan** `BaseService`.
- **Rotasi refresh token** dan **session management per-perangkat** — modelnya (`SessionSetting`) ada, layarnya belum digenerate.
- **Rate limiting** pada endpoint login.
