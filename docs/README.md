# ERP Knowledge Base

> **ERP Blueprint & Technical Documentation**

Selamat datang di **ERP Knowledge Base**, pusat dokumentasi resmi untuk seluruh pengembangan ERP.

Dokumentasi ini berfungsi sebagai **single source of truth** bagi seluruh tim pengembangan, Business Analyst, QA, DevOps, dan Management dalam merancang, mengembangkan, serta memelihara sistem ERP.

---

# Purpose

Knowledge Base ini dibuat untuk memastikan bahwa setiap modul ERP memiliki dokumentasi yang konsisten sebelum dan selama proses pengembangan.

Dokumentasi mencakup:

* Product Vision
* Business Process
* Functional Requirements
* Technical Architecture
* Database Design
* API Standards
* User Interface
* Workflow
* Permission Model
* Development Standards
* Deployment Guide
* Product Roadmap

---

# Documentation Structure

```
docs/

00-overview/
01-architecture/
02-modules/
03-ui-ux/
04-api/
05-database/
06-deployment/
07-development/
08-decisions/
09-release/
```

---

# Development Workflow

Setiap fitur baru mengikuti alur berikut:

```
Idea
    ↓
Blueprint Documentation
    ↓
Architecture Review
    ↓
Database Design
    ↓
API Design
    ↓
Frontend Development
    ↓
Backend Development
    ↓
Testing
    ↓
Release
    ↓
Documentation Update
```

---

# Documentation Principles

* Documentation First
* Business Driven Design
* Consistent Architecture
* Living Documentation
* Single Source of Truth

---

# Versioning

Dokumentasi mengikuti Semantic Versioning (SemVer).

* MAJOR → Perubahan besar
* MINOR → Penambahan fitur
* PATCH → Perbaikan bug atau dokumentasi

Seluruh perubahan dicatat pada:

* `00-overview/Changelog.md`

---

# Getting Started

Install dependency:

```bash
pip install mkdocs mkdocs-material pymdown-extensions
```

Menjalankan dokumentasi:

```bash
mkdocs serve
```

Build static site:

```bash
mkdocs build
```

Dokumentasi akan tersedia di:

```
http://127.0.0.1:8000
```

---

# Notes

Knowledge Base ini merupakan **living documentation** dan harus diperbarui setiap kali terdapat perubahan pada arsitektur, modul, API, database, ataupun business process.

Dokumentasi merupakan bagian dari proses pengembangan dan memiliki prioritas yang sama dengan source code.
