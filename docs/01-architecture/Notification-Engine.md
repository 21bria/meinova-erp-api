# Notification Engine

> Version: 1.0
> Status: Draft
> Module: Core Platform
> Priority: High

---

## Purpose

Dokumen ini mendefinisikan arsitektur Notification Engine pada platform ERP.

Notification Engine bertanggung jawab untuk mengirim, menyimpan, menampilkan, dan mengelola notifikasi dari seluruh modul ERP kepada pengguna yang tepat, pada waktu yang tepat, melalui channel yang tepat.

Notification Engine menjadi bagian penting dari Digital Workspace karena membantu user mengetahui informasi penting, approval, task, reminder, escalation, dan aktivitas sistem secara real-time.

---

## Scope

Dokumen ini mencakup:

* Notification Strategy
* Notification Types
* Notification Channels
* In-App Notification
* Email Notification
* Push Notification
* WhatsApp / SMS Notification
* Notification Priority
* Notification Template
* Notification Preference
* Integration with Workflow Engine
* Integration with Task Engine
* API Contract
* Database Design
* Multi-Tenant Rules
* Future Roadmap

---

# Notification Strategy

Platform menggunakan pendekatan **Centralized Notification Engine**.

Seluruh modul tidak mengirim notifikasi secara langsung, tetapi memanggil Notification Engine.

```text
Business Module
      ↓
Notification Engine
      ↓
Notification Channel
      ↓
User
```

Dengan pendekatan ini, format, permission, preference, dan audit notifikasi dapat dikontrol secara konsisten.

---

# Core Concepts

## Notification Event

Notification Event adalah peristiwa yang memicu notifikasi.

Contoh:

* Leave request submitted
* Purchase request approved
* Payroll run waiting approval
* Travel request ticket issued
* Task assigned
* Workflow escalated
* Document uploaded
* System alert

---

## Notification Type

Jenis notifikasi:

* INFO
* SUCCESS
* WARNING
* ERROR
* APPROVAL
* TASK
* REMINDER
* ESCALATION
* SYSTEM

---

## Notification Priority

Prioritas notifikasi:

* LOW
* NORMAL
* HIGH
* CRITICAL

Contoh:

* LOW: informasi umum
* NORMAL: update status
* HIGH: approval penting
* CRITICAL: kegagalan sistem atau deadline terlewat

---

## Notification Channels

Notification Engine mendukung beberapa channel:

* In-App
* Email
* Push Notification
* SMS
* WhatsApp
* Webhook

Tahap awal fokus pada:

* In-App Notification
* Email Notification

---

# In-App Notification

In-App Notification muncul di:

* Header Notification Bell
* Dashboard Notification Widget
* My Work Inbox
* Notification Center

Fitur:

* Read / Unread
* Mark as Read
* Mark All as Read
* Filter by Type
* Filter by Module
* Search Notification

---

# Email Notification

Email digunakan untuk:

* Approval penting
* Reminder
* Escalation
* System alert
* Summary harian / mingguan

Email harus menggunakan template standar agar konsisten.

---

# Notification Template

Setiap notifikasi memiliki template.

Contoh:

```text
Title: Purchase Request Waiting Approval
Message: PR-00018 is waiting for your approval.
Action: Open Purchase Request
```

Template dapat berbeda per module dan per channel.

---

# Notification Preference

User dapat mengatur preferensi notifikasi.

Contoh:

* Receive email for approval
* Receive email for task reminder
* Disable low-priority notification
* Daily summary only
* Instant notification

---

# Integration

Notification Engine terintegrasi dengan:

* Workflow Engine
* Task Engine
* Dashboard Engine
* Authorization Engine
* Audit Engine
* AI Engine

Contoh integrasi:

```text
Workflow Submitted
      ↓
Create Task
      ↓
Send Notification
      ↓
Show on Dashboard
```

---

# Backend Architecture

```text
Business Event
      ↓
Notification Service
      ↓
Notification Model
      ↓
Channel Dispatcher
      ↓
User Delivery
```

---

# Database Design

## Notification

Field utama:

```text
tenant
recipient
title
message
notification_type
priority
module
reference_type
reference_id
action_url
is_read
read_at
created_at
```

---

## NotificationTemplate

Field utama:

```text
code
module
channel
title_template
message_template
is_active
```

---

## NotificationPreference

Field utama:

```text
tenant
user
channel
notification_type
is_enabled
```

---

# API Contract

Endpoint awal:

```text
GET  /api/core/notifications/
GET  /api/core/notifications/unread-count/
POST /api/core/notifications/{id}/read/
POST /api/core/notifications/mark-all-read/
DELETE /api/core/notifications/{id}/
```

Future endpoint:

```text
GET  /api/core/notifications/preferences/
PATCH /api/core/notifications/preferences/
POST /api/core/notifications/test/
```

---

# Business Rules

* Notifikasi harus selalu memiliki recipient.
* Notifikasi harus berada dalam konteks tenant.
* Notifikasi tidak boleh dikirim ke user tanpa permission terkait.
* Notifikasi critical tidak boleh dinonaktifkan.
* Notifikasi dapat memiliki action URL.
* Notifikasi workflow harus terkait dengan workflow/task.
* Notifikasi harus dapat diaudit.

---

# Multi-Tenant Rules

Seluruh notifikasi bersifat tenant-aware.

Field wajib:

```text
tenant
recipient
```

User tidak dapat melihat notifikasi tenant lain.

---

# Notification Flow

```text
Event Occurs
    ↓
Create Notification
    ↓
Check User Preference
    ↓
Check Permission
    ↓
Dispatch Channel
    ↓
Store Notification
    ↓
Show in Dashboard
```

---

# Future Roadmap

## Phase 1

* In-App Notification
* Notification Bell
* Dashboard Notification Widget
* Unread Count
* Mark as Read

## Phase 2

* Email Notification
* Notification Template
* User Preference

## Phase 3

* Reminder
* Escalation
* Daily Summary
* Weekly Summary

## Phase 4

* Push Notification
* WhatsApp Notification
* SMS Notification
* Webhook Notification

## Phase 5

* AI Notification Summary
* Smart Notification Filtering
* Notification Priority Recommendation

---

## References

Dokumen yang berkaitan:

* Workflow Engine
* Task Engine
* Dashboard Engine
* Authorization
* AI Engine
* Audit Engine

---

## Notes

Notification Engine merupakan layanan inti yang digunakan oleh seluruh modul ERP.

Setiap modul tidak diperbolehkan mengirim notifikasi secara langsung tanpa melalui Notification Engine agar format, preference, security, dan audit trail tetap konsisten.
