# Search Engine

> Version: 1.0
> Status: Draft
> Module: Core Platform
> Priority: High

---

## Purpose

Dokumen ini mendefinisikan arsitektur Search Engine pada platform ERP.

Search Engine bertanggung jawab untuk menyediakan pencarian cepat, konsisten, dan aman di seluruh modul ERP melalui fitur **Global Search**, **Module Search**, dan **Smart Search**.

Search Engine membantu pengguna menemukan data, dokumen, transaksi, task, approval, menu, dan informasi penting tanpa harus membuka banyak modul secara manual.

---

## Scope

Dokumen ini mencakup:

* Search Strategy
* Global Search
* Module Search
* Menu Search
* Recent Search
* Search Indexing
* Permission-Based Search
* Tenant-Aware Search
* Search Ranking
* API Contract
* Database Design
* UI/UX Direction
* AI Search
* Future Roadmap

---

# Search Strategy

Platform menggunakan pendekatan **Centralized Search Engine**.

Seluruh modul dapat mendaftarkan data yang dapat dicari melalui Search Registry.

```text
Business Module
      ↓
Search Registry
      ↓
Search Index
      ↓
Search API
      ↓
Global Search UI
```

---

# Core Concepts

## Global Search

Global Search digunakan untuk mencari data lintas modul.

Contoh pencarian:

```text
John
```

Hasil dapat berupa:

* Employee
* Leave Request
* Payroll
* Purchase Request
* Task
* Document
* Asset

---

## Module Search

Module Search digunakan untuk pencarian dalam modul tertentu.

Contoh:

* Employee Search
* Purchase Request Search
* Journal Search
* Inventory Search
* Task Search

---

## Menu Search

Menu Search digunakan untuk mencari halaman atau fitur.

Contoh:

```text
payroll
```

Hasil:

* Payroll Dashboard
* Payroll Run
* Payslip
* Tax
* BPJS

---

## Recent Search

Sistem dapat menyimpan pencarian terakhir user untuk meningkatkan produktivitas.

Contoh:

* Last searched employee
* Last opened PR
* Recently viewed document

---

# Search Registry

Setiap modul dapat mendaftarkan searchable resource.

Contoh:

```text
Employee
PurchaseRequest
JournalEntry
TravelRequest
Task
Document
Asset
```

Setiap resource mendefinisikan:

* Source model
* Title field
* Description field
* URL
* Permission
* Search fields
* Module
* Icon
* Result type

---

# Permission-Based Search

Search Engine wajib menghormati permission user.

User hanya dapat melihat hasil pencarian yang memiliki permission dan scope yang sesuai.

Contoh:

* HR hanya melihat employee sesuai scope.
* Finance hanya melihat journal sesuai permission.
* User biasa hanya melihat data miliknya sendiri.

---

# Tenant-Aware Search

Search Engine selalu berjalan dalam konteks tenant.

Semua hasil pencarian harus berasal dari tenant yang sama dengan request user.

User tidak boleh melihat hasil dari tenant lain.

---

# Search Ranking

Hasil pencarian dapat diprioritaskan berdasarkan:

* Exact match
* Recently opened
* Frequently used
* Module priority
* User role
* Favorite menus
* Permission relevance

---

# Backend Architecture

```text
Search Query
      ↓
Search Service
      ↓
Permission Filter
      ↓
Scope Filter
      ↓
Ranking
      ↓
Search Result
```

---

# Database Design

## SearchIndex

Future model:

```text
tenant
resource_type
resource_id
title
description
module
url
keywords
permission
created_at
updated_at
```

---

## SearchHistory

Future model:

```text
tenant
user
query
result_type
result_id
created_at
```

---

# API Contract

Endpoint awal:

```text
GET /api/core/search/
```

Query parameter:

```text
q
module
type
limit
```

Contoh:

```text
GET /api/core/search/?q=john&limit=10
```

Future endpoint:

```text
GET    /api/core/search/recent/
DELETE /api/core/search/recent/
GET    /api/core/search/suggestions/
```

---

# UI / UX Direction

Search tersedia pada:

* Global Header
* Dashboard Workspace
* Module Header
* Command Palette

Tampilan hasil pencarian:

```text
Employee
John Doe
HR • Employee Master

Purchase Request
PR-00018
SCM • Purchase Request
```

---

# AI Search

Future AI Search memungkinkan user bertanya menggunakan bahasa natural.

Contoh:

```text
Tampilkan karyawan yang kontraknya habis bulan depan.
```

atau:

```text
PR apa saja yang belum di-approve?
```

AI Search akan menggabungkan:

* Search Engine
* Authorization Engine
* Data Query
* AI Assistant

---

# Business Rules

* Search harus cepat.
* Search harus tenant-aware.
* Search harus permission-aware.
* Search tidak boleh menampilkan data tanpa izin.
* Search harus mencatat history jika fitur recent search aktif.
* Search harus bisa digunakan lintas modul.

---

# Future Roadmap

## Phase 1

* Global Search UI
* Menu Search
* Module Search
* Permission-Aware Search

## Phase 2

* Search History
* Recent Items
* Suggestions
* Frequently Opened

## Phase 3

* Search Index Table
* Background Indexing
* Full-Text Search

## Phase 4

* AI Search
* Natural Language Query
* Semantic Search
* Smart Recommendation

---

## References

Dokumen yang berkaitan:

* Dashboard Engine
* Authorization
* Multi-Tenant
* API Standards
* AI Engine

---

## Notes

Search Engine merupakan fitur produktivitas inti pada ERP.

Search harus dirancang sebagai layanan platform, bukan fitur per modul, agar seluruh data ERP dapat ditemukan dengan pola yang konsisten, aman, dan cepat.
