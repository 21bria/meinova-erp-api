# Multi-Tenant Architecture

> Version: 1.0
> Status: Active
> Module: Core Platform
> Priority: Critical

---

## Purpose

Dokumen ini mendefinisikan arsitektur Multi-Tenant yang digunakan oleh platform ERP.

Tujuan utama implementasi Multi-Tenant adalah memungkinkan satu platform ERP melayani banyak perusahaan (tenant) secara aman, terisolasi, dan efisien tanpa mengorbankan performa maupun fleksibilitas pengembangan.

Dokumen ini menjadi acuan bagi seluruh pengembangan backend, frontend, database, deployment, dan integrasi.

---

## Scope

Dokumen ini mencakup:

* Multi-Tenant Strategy
* Tenant Lifecycle
* Database Architecture
* Schema Isolation
* Shared Data
* Tenant Data
* Domain Routing
* Authentication
* Authorization
* Migration Strategy
* Provisioning
* Backup & Recovery
* Deployment Strategy
* Security
* Best Practices
* Future Roadmap

---

# Multi-Tenant Strategy

Platform menggunakan pendekatan:

**Shared Application + Separate PostgreSQL Schema per Tenant**

Setiap tenant memiliki schema PostgreSQL sendiri sehingga data antar perusahaan benar-benar terisolasi.

Semua tenant menggunakan codebase, API, dan deployment yang sama.

---

# Architecture Overview

```text
                    ERP Platform
                         │
                Reverse Proxy / Nginx
                         │
                  Tenant Resolver
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   company-a        company-b        company-c
        │                │                │
   Schema A         Schema B         Schema C
        │                │                │
        └──────────── PostgreSQL ─────────┘
```

---

# Tenant Isolation

Setiap tenant memiliki:

* Users
* Employees
* Organization
* Payroll
* Finance
* Inventory
* Workflow
* Dashboard
* Reports

Tenant tidak dapat mengakses data tenant lain.

---

# Shared Components

Data yang digunakan bersama seluruh tenant ditempatkan pada **public schema**.

Contoh:

* Tenant Registry
* Subscription
* Plan
* Domain
* License
* Global Configuration

---

# Tenant Components

Data operasional berada pada schema masing-masing tenant.

Contoh:

* Employee
* Payroll
* Finance
* Dashboard
* Favorite Apps
* Workflow
* Notifications
* Tasks
* Reports

---

# Domain Routing

Setiap tenant diakses melalui domain atau subdomain.

Contoh:

```text
company-a.example.com
company-b.example.com
company-c.example.com
```

Tenant Resolver menentukan schema yang digunakan berdasarkan domain tersebut.

---

# Authentication

Autentikasi dilakukan setelah tenant berhasil diidentifikasi.

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
Authorize Request
```

---

# Authorization

Hak akses ditentukan berdasarkan:

* Role
* Permission
* Department
* Site
* Business Unit

Seluruh permission berlaku di dalam tenant masing-masing.

---

# Database Strategy

Menggunakan PostgreSQL Schema-Based Multi-Tenant.

Keuntungan:

* Isolasi data yang kuat.
* Backup per tenant.
* Restore per tenant.
* Migrasi lebih mudah.
* Skalabilitas tinggi.

---

# Migration Strategy

Perubahan struktur database dilakukan menggunakan migration tenant.

Urutan:

```text
Shared Migration
      ↓
Tenant Migration
      ↓
Seeder
```

---

# Tenant Provisioning

Saat tenant baru dibuat:

1. Membuat schema baru.
2. Menjalankan migration tenant.
3. Menjalankan seed data.
4. Membuat administrator tenant.
5. Mengaktifkan domain tenant.

---

# Backup Strategy

Backup dapat dilakukan pada beberapa tingkat:

* Backup seluruh database.
* Backup per schema (tenant).
* Backup konfigurasi shared.
* Backup media dan file.

---

# Security

Prinsip keamanan:

* Isolasi data antar tenant.
* Validasi tenant pada setiap request.
* Permission berbasis role.
* Audit trail.
* Enkripsi komunikasi menggunakan HTTPS.

---

# Development Guidelines

Seluruh modul baru harus:

* Mendukung Multi-Tenant.
* Tidak menggunakan data lintas tenant.
* Menggunakan tenant context pada setiap query.
* Memastikan permission selalu diterapkan.

---

# Advantages

Pendekatan ini memberikan:

* Satu codebase untuk semua tenant.
* Deployment lebih sederhana.
* Biaya operasional lebih rendah.
* Skalabilitas tinggi.
* Kemudahan maintenance.
* Kemudahan onboarding tenant baru.

---

# Future Roadmap

Pengembangan selanjutnya meliputi:

* Tenant Template
* Tenant Cloning
* Self-Service Tenant Provisioning
* Resource Quota
* Billing & Subscription
* Monitoring per Tenant
* Cross-Tenant Analytics (opsional dan terkendali)

---

## References

Dokumen yang berkaitan:

* System Architecture
* Authentication
* Authorization
* Dashboard Engine
* Workflow Engine
* Deployment
* Database Design

---

## Notes

Multi-Tenant merupakan fondasi utama platform ERP. Setiap modul, layanan, dan fitur baru wajib dirancang agar sepenuhnya kompatibel dengan arsitektur Multi-Tenant yang telah ditetapkan.

Perubahan terhadap strategi Multi-Tenant harus melalui Architecture Decision Record (ADR) karena akan berdampak pada seluruh sistem.
