# Authentication

> Version: 1.0
> Status: Active
> Module: Core Platform
> Priority: Critical

---

## Purpose

Dokumen ini mendefinisikan mekanisme Authentication yang digunakan oleh platform ERP.

Authentication bertanggung jawab untuk memverifikasi identitas pengguna sebelum diberikan akses ke sistem. Dokumen ini menjadi acuan implementasi login, logout, session management, token management, serta mekanisme keamanan autentikasi pada seluruh aplikasi ERP.

---

## Scope

Dokumen ini mencakup:

* Authentication Strategy
* Login Flow
* Logout Flow
* JWT Authentication
* Refresh Token
* Cookie Authentication
* Session Management
* Password Management
* Multi-Factor Authentication (Future)
* Tenant Authentication
* API Authentication
* Security Best Practices
* Future Roadmap

---

# Authentication Strategy

Platform menggunakan **JWT Authentication** dengan **HTTP Only Cookie** sebagai media penyimpanan token.

Strategi ini dipilih untuk:

* Mengurangi risiko XSS.
* Mendukung SPA (Nuxt).
* Mendukung API.
* Mendukung Multi-Tenant.
* Memudahkan refresh session.

---

# Login Flow

```text
User
   ↓
Login Page
   ↓
API Authentication
   ↓
Validate Credential
   ↓
Resolve Tenant
   ↓
Generate Access Token
   ↓
Generate Refresh Token
   ↓
Store HTTP Only Cookie
   ↓
Dashboard
```

---

# Logout Flow

```text
User
   ↓
Logout
   ↓
Invalidate Refresh Token
   ↓
Clear Cookie
   ↓
Redirect Login
```

---

# Token Strategy

Platform menggunakan dua jenis token:

### Access Token

Digunakan untuk mengakses API.

Karakteristik:

* Short Lifetime
* Tidak disimpan di Local Storage
* Dikirim otomatis melalui Cookie

---

### Refresh Token

Digunakan untuk memperoleh Access Token baru.

Karakteristik:

* Lifetime lebih panjang
* HTTP Only
* Secure Cookie
* Dapat di-rotate

---

# Cookie Strategy

Cookie menggunakan konfigurasi berikut:

* HTTP Only
* Secure (Production)
* SameSite
* Expiration sesuai kebijakan sistem

Cookie tidak dapat diakses melalui JavaScript.

---

# Session Management

Sistem mendukung:

* Login
* Logout
* Session Refresh
* Session Expired
* Multiple Device Login
* Force Logout (Future)

---

# Password Management

Mendukung:

* Password Hashing
* Password Reset
* Password Change
* Password Expiration (Optional)
* Password Policy

---

# Multi-Tenant Authentication

Sebelum autentikasi dilakukan, sistem menentukan tenant berdasarkan domain atau subdomain.

Alur:

```text
Request
   ↓
Resolve Tenant
   ↓
Select Schema
   ↓
Authenticate User
   ↓
Issue Token
```

Setiap token hanya berlaku pada tenant tempat pengguna melakukan login.

---

# API Authentication

Seluruh endpoint yang bersifat private wajib melalui proses autentikasi.

Contoh:

```text
POST //api/accounts/auth/login/
POST /api/auth/logout/
POST /api/accounts/auth/refresh/
GET  /api/auth/profile/
POST /api/auth/change-password/
```

---

# Security Principles

Authentication mengikuti prinsip:

* HTTPS Only
* HTTP Only Cookie
* Secure Cookie
* Token Rotation
* Password Hashing
* Brute Force Protection
* CSRF Protection
* Session Validation

---

# Future Roadmap

Pengembangan selanjutnya meliputi:

* Multi-Factor Authentication (MFA)
* Single Sign-On (SSO)
* OAuth2 Integration
* OpenID Connect
* Active Directory / LDAP Integration
* Device Management
* Login History
* Suspicious Login Detection
* Passwordless Login

---

## References

Dokumen yang berkaitan:

* System Architecture
* Multi-Tenant
* Authorization
* API Standards
* Security Guidelines

---

## Notes

Authentication merupakan lapisan keamanan pertama pada platform ERP. Seluruh modul dan layanan wajib menggunakan mekanisme autentikasi yang telah ditetapkan dan tidak diperbolehkan membuat mekanisme login tersendiri di luar standar platform.

Perubahan terhadap strategi autentikasi harus melalui proses Architecture Review karena berdampak pada seluruh sistem.
