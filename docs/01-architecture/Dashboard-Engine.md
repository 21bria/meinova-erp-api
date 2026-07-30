# Dashboard Engine

> Version: 1.0  
> Status: Draft  
> Module: Core Platform  
> Priority: High  

---

## 1. Vision

Dashboard Engine adalah fondasi workspace modern pada ERP.

Dashboard bukan hanya halaman statistik, tetapi menjadi **personal digital workspace** yang membantu user melihat pekerjaan, prioritas, approval, notifikasi, aplikasi favorit, menu favorit, dan KPI dalam satu halaman.

---

## 2. Business Problem

Banyak ERP tradisional memiliki dashboard yang kaku.

Masalah yang ingin diselesaikan:

- User harus membuka banyak menu untuk melihat pekerjaan.
- Approval tersebar di banyak modul.
- Shortcut aplikasi tidak personal.
- Dashboard tidak bisa dikustomisasi oleh user.
- Management sulit melihat insight secara cepat.
- Admin IT sulit mengatur default dashboard per role.

---

## 3. Solution

Dashboard Engine menyediakan workspace yang:

- Personal per user.
- Mengikuti role dan permission.
- Mendukung Favorite Apps.
- Mendukung Favorite Menus.
- Mendukung Widget Registry.
- Mendukung User Dashboard Layout.
- Mendukung Dashboard Template untuk Admin IT.
- Siap dikembangkan ke KPI Engine dan AI Insight.

---

## 4. Core Concepts

### 4.1 Favorite Apps

Daftar aplikasi/modul yang sering digunakan user.

Contoh:

- Organization
- Human Resources
- Payroll
- Supply Chain
- Finance
- Reports
- Workflow

---

### 4.2 Favorite Menus

Shortcut ke halaman spesifik.

Contoh:

- Employee Master
- Attendance
- Payroll Run
- Purchase Request
- Journal Entry

---

### 4.3 Dashboard Widgets

Komponen dashboard yang dapat ditampilkan berdasarkan permission.

Contoh:

- KPI Summary
- My Tasks
- Pending Approval
- Notifications
- Quick Actions
- Executive Insight
- Chart Widget

---

### 4.4 User Layout

Layout dashboard disimpan per tenant dan per user.

User dapat:

- Mengatur urutan widget.
- Menyembunyikan widget.
- Mengubah ukuran widget.
- Menyimpan workspace pribadi.
- Reset ke default template.

---

### 4.5 Dashboard Template

Admin IT dapat membuat default dashboard berdasarkan role.

Contoh template:

- User Dashboard
- Manager Dashboard
- HR Dashboard
- Finance Dashboard
- Executive Dashboard
- Admin IT Dashboard

---

## 5. Current Implementation

Backend saat ini menggunakan model:

```txt
DashboardWidget
UserDashboardLayout
FavoriteApp
FavoriteMenu