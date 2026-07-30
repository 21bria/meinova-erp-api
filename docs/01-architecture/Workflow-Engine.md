# Workflow Engine

> Version: 1.0
> Status: Active
> Module: Core Platform
> Priority: Critical

---

## Purpose

Dokumen ini mendefinisikan arsitektur Workflow Engine yang digunakan oleh seluruh platform ERP.

Workflow Engine bertanggung jawab untuk mengelola proses bisnis, approval, task assignment, delegasi, notifikasi, audit trail, serta otomatisasi alur kerja lintas modul.

Workflow Engine merupakan fondasi utama yang memastikan seluruh proses bisnis berjalan secara konsisten, terstruktur, dan dapat diaudit.

---

## Scope

Dokumen ini mencakup:

* Workflow Strategy
* Workflow Definition
* Approval Flow
* Task Assignment
* Workflow State
* Delegation
* Escalation
* Notification Integration
* Audit Trail
* API Contract
* Database Design
* Multi-Tenant Rules
* Future Roadmap

---

# Workflow Strategy

Platform menggunakan **Configurable Workflow Engine**.

Setiap modul dapat menggunakan engine yang sama tanpa membuat workflow baru.

Workflow bersifat:

* Reusable
* Configurable
* Multi-Level
* Multi-Module
* Multi-Tenant

---

# Core Concepts

### Workflow Definition

Workflow merupakan definisi proses bisnis.

Contoh:

* Leave Request
* Purchase Request
* Purchase Order
* Travel Request
* Recruitment
* Payroll Approval
* Journal Approval
* Incident Investigation

---

### Workflow Step

Setiap workflow terdiri dari beberapa langkah.

Contoh:

```text
Employee
    ↓
Supervisor
    ↓
Department Manager
    ↓
HR
    ↓
Completed
```

---

### Workflow Action

Setiap langkah memiliki aksi.

Contoh:

* Submit
* Approve
* Reject
* Return
* Cancel
* Escalate
* Delegate
* Close

---

### Workflow State

Status proses.

Contoh:

* Draft
* Waiting Approval
* Approved
* Rejected
* Returned
* Cancelled
* Completed

---

### Task Assignment

Workflow secara otomatis membuat task.

Task muncul pada:

* My Work
* Dashboard
* Notification Center

---

### Delegation

User dapat mendelegasikan approval kepada pengguna lain.

Contoh:

Manager sedang cuti.

Approval otomatis dialihkan ke Acting Manager.

---

### Escalation

Jika approval melewati batas waktu:

```text
2 Days
     ↓
Reminder
     ↓
Escalation
     ↓
Higher Manager
```

---

## Current Implementation

Workflow Engine akan menjadi layanan bersama (shared service) yang digunakan seluruh modul.

Contoh modul:

* HR
* Payroll
* Finance
* SCM
* Mining
* Safety

---

## Backend Architecture

```text
Business Module
        ↓
Workflow Service
        ↓
Task Engine
        ↓
Notification Engine
        ↓
Audit Engine
```

---

## Database Design

### Workflow Definition

Field utama:

```text
code
name
module
description
is_active
```

---

### Workflow Step

Field utama:

```text
workflow
step_order
role
approval_type
```

---

### Workflow Instance

Field utama:

```text
workflow
reference_type
reference_id
status
created_by
```

---

### Workflow Task

Field utama:

```text
instance
assigned_to
status
due_date
completed_at
```

---

### Workflow History

Field utama:

```text
workflow
user
action
remarks
created_at
```

---

## API Contract

Contoh endpoint:

```text
POST /api/workflows/start/
GET  /api/workflows/
GET  /api/workflows/{id}/
POST /api/workflows/{id}/approve/
POST /api/workflows/{id}/reject/
POST /api/workflows/{id}/return/
POST /api/workflows/{id}/delegate/
POST /api/workflows/{id}/cancel/
```

---

## Business Rules

Workflow harus memenuhi aturan berikut:

* Selalu memiliki creator.
* Selalu memiliki history.
* Selalu memiliki audit trail.
* Mendukung multi-level approval.
* Mendukung parallel approval (future).
* Mendukung sequential approval.
* Mendukung delegation.
* Mendukung escalation.
* Mendukung reminder.

---

## Integration

Workflow Engine terintegrasi dengan:

* Dashboard Engine
* Task Engine
* Notification Engine
* Authorization Engine
* Audit Engine
* AI Engine

---

## Multi-Tenant Rules

Workflow selalu berjalan dalam konteks tenant.

Data workflow tidak boleh diakses tenant lain.

Semua instance workflow harus menyimpan:

```text
tenant
created_by
organization
```

---

## Workflow Execution

```text
User Submit
      ↓
Workflow Engine
      ↓
Create Workflow Instance
      ↓
Generate Task
      ↓
Send Notification
      ↓
Waiting Approval
      ↓
Next Step
      ↓
Completed
```

---

## Future Roadmap

### Phase 1

* Workflow Definition
* Sequential Approval
* Task Creation
* History
* Notification

### Phase 2

* Delegation
* Reminder
* Escalation
* SLA Monitoring

### Phase 3

* Parallel Approval
* Conditional Workflow
* Dynamic Routing
* Workflow Versioning

### Phase 4

* Visual Workflow Designer
* Drag & Drop Builder
* BPMN Import / Export

### Phase 5

* AI Workflow Recommendation
* Predictive Approval
* Workflow Analytics
* Process Optimization

---

## References

Dokumen yang berkaitan:

* Dashboard Engine
* Notification Engine
* Task Engine
* Authorization
* AI Engine
* System Architecture

---

## Notes

Workflow Engine merupakan salah satu layanan inti (Core Service) pada platform ERP.

Seluruh modul wajib menggunakan Workflow Engine yang sama agar proses bisnis, approval, task, audit, dan notifikasi tetap konsisten di seluruh sistem.

Perubahan terhadap Workflow Engine harus melalui Architecture Review karena akan berdampak pada seluruh platform.
