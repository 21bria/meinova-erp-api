# Task Engine

> Version: 1.0
> Status: Active
> Module: Core Platform
> Priority: Critical

---

## Purpose

Dokumen ini mendefinisikan arsitektur Task Engine yang digunakan oleh platform ERP.

Task Engine bertanggung jawab untuk membuat, mengelola, mendistribusikan, memantau, dan menyelesaikan seluruh tugas (Tasks) yang dihasilkan dari proses bisnis, workflow, approval, maupun aktivitas sistem.

Task Engine menjadi pusat aktivitas pengguna melalui fitur **My Work**, sehingga seluruh pekerjaan dari berbagai modul dapat dikelola dalam satu tempat.

---

## Scope

Dokumen ini mencakup:

* Task Strategy
* Task Lifecycle
* Task Assignment
* My Work
* Task Priority
* Task Status
* Due Date & SLA
* Delegation
* Escalation
* Integration with Workflow
* Integration with Notification
* API Contract
* Database Design
* Multi-Tenant Rules
* Future Roadmap

---

# Task Strategy

Platform menggunakan **Centralized Task Engine**.

Seluruh modul membuat tugas melalui Task Engine, bukan membuat tabel task masing-masing.

```text
Business Module
      ↓
Workflow Engine
      ↓
Task Engine
      ↓
My Work
```

---

# Core Concepts

## My Work

Seluruh tugas pengguna ditampilkan pada satu halaman.

Contoh:

* Leave Approval
* Purchase Approval
* Journal Approval
* Travel Approval
* Recruitment Interview
* Medical Check Reminder
* Equipment Inspection
* Daily Production Review

User tidak perlu membuka setiap modul untuk mengetahui pekerjaannya.

---

## Task Assignment

Task dapat diberikan kepada:

* Individual User
* Role
* Department
* Team
* Position

---

## Task Status

Status task:

* New
* Assigned
* In Progress
* Waiting Approval
* Completed
* Rejected
* Cancelled
* Expired

---

## Task Priority

Prioritas:

* Low
* Normal
* High
* Critical

Prioritas digunakan untuk menentukan urutan pekerjaan di Dashboard dan My Work.

---

## Due Date & SLA

Task dapat memiliki:

* Due Date
* Reminder Date
* SLA Duration

Jika melewati SLA, Task Engine dapat memicu Reminder atau Escalation melalui Notification Engine.

---

## Task Delegation

Apabila pengguna berhalangan, task dapat didelegasikan kepada pengguna lain sesuai kebijakan organisasi.

---

## Task Escalation

Task yang tidak diselesaikan dalam batas waktu tertentu dapat:

* Mengirim reminder.
* Diteruskan ke atasan.
* Dicatat sebagai keterlambatan.
* Diprioritaskan ulang.

---

# Integration

Task Engine terintegrasi dengan:

* Workflow Engine
* Dashboard Engine
* Notification Engine
* Authorization Engine
* Audit Engine
* AI Engine

---

# Backend Architecture

```text
Business Event
      ↓
Workflow Engine
      ↓
Task Engine
      ↓
Notification
      ↓
Dashboard
```

---

# Database Design

## Task

Field utama:

```text
tenant
title
description
module
reference_type
reference_id
assigned_to
assigned_role
priority
status
due_date
completed_at
```

---

## Task History

Field utama:

```text
task
action
user
remarks
created_at
```

---

## Task Comment

Future:

```text
task
comment
user
attachment
created_at
```

---

# API Contract

Endpoint awal:

```text
GET  /api/core/tasks/
GET  /api/core/tasks/my-work/
GET  /api/core/tasks/{id}/
PATCH /api/core/tasks/{id}/
POST /api/core/tasks/{id}/complete/
POST /api/core/tasks/{id}/delegate/
POST /api/core/tasks/{id}/cancel/
```

Future endpoint:

```text
POST /api/core/tasks/bulk-complete/
POST /api/core/tasks/bulk-assign/
GET  /api/core/tasks/dashboard/
```

---

# Business Rules

* Setiap task harus memiliki owner.
* Task selalu terkait dengan tenant.
* Task dapat berasal dari Workflow maupun modul lain.
* Task wajib memiliki audit history.
* Task dapat memiliki attachment dan komentar.
* Task dapat diarsipkan setelah selesai.

---

# Multi-Tenant Rules

Task disimpan berdasarkan:

```text
tenant
assigned_to
```

Pengguna hanya dapat melihat task yang menjadi hak aksesnya.

---

# Task Lifecycle

```text
Created
    ↓
Assigned
    ↓
In Progress
    ↓
Waiting Approval
    ↓
Completed
```

Alternatif:

```text
Created
    ↓
Rejected

atau

Created
    ↓
Cancelled

atau

Created
    ↓
Expired
```

---

# Dashboard Integration

Task Engine menyediakan data untuk widget:

* My Work
* Pending Tasks
* Overdue Tasks
* Upcoming Deadlines
* Recent Activity

Dashboard selalu mengambil informasi task dari Task Engine.

---

# AI Integration

AI dapat membantu pengguna melalui:

* Ringkasan tugas hari ini.
* Prioritas pekerjaan.
* Prediksi keterlambatan.
* Rekomendasi penyelesaian task.
* Daily Work Summary.

---

# Future Roadmap

## Phase 1

* My Work
* Task Assignment
* Task Status
* Due Date

## Phase 2

* Reminder
* Escalation
* Task Comment
* Attachment

## Phase 3

* Task Timeline
* Calendar View
* Kanban View
* Bulk Actions

## Phase 4

* AI Task Summary
* Smart Prioritization
* Predictive SLA
* Workload Balancing

---

## References

Dokumen yang berkaitan:

* Workflow Engine
* Notification Engine
* Dashboard Engine
* Authorization
* AI Engine
* Audit Engine

---

## Notes

Task Engine merupakan pusat aktivitas pengguna pada platform ERP.

Seluruh tugas operasional harus melalui Task Engine agar Dashboard Workspace, Notification Engine, Workflow Engine, dan AI Engine dapat bekerja secara terintegrasi dan konsisten.

Task Engine menjadi fondasi fitur **My Work**, yaitu halaman utama yang digunakan pengguna setiap hari untuk melihat, mengelola, dan menyelesaikan seluruh pekerjaannya.
