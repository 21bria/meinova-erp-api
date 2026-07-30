# Widget Engine

> Version: 1.0
> Status: Draft
> Module: Core Platform
> Priority: High

---

## Purpose

Dokumen ini mendefinisikan arsitektur Widget Engine pada platform ERP.

Widget Engine bertanggung jawab untuk mengelola daftar widget, konfigurasi widget, permission widget, data source widget, dan rendering widget pada Dashboard Workspace.

Dokumen ini menjadi acuan pengembangan dashboard yang modular, personal, dan dapat dikustomisasi oleh user maupun Admin IT.

---

## Scope

Dokumen ini mencakup:

* Widget Strategy
* Widget Registry
* Widget Types
* Widget Permission
* Widget Configuration
* Widget Data Source
* Widget Layout
* Widget Rendering
* API Contract
* Database Design
* Multi-Tenant Rules
* Future Roadmap

---

## Widget Strategy

Widget Engine menggunakan pendekatan **Registry-Based Widget Architecture**.

Backend menyimpan metadata widget.

Frontend bertanggung jawab melakukan rendering berdasarkan registry komponen.

---

## Core Concepts

### Widget Registry

Widget Registry adalah daftar master widget yang tersedia pada sistem.

Contoh widget:

* KPI Summary
* Favorite Apps
* Favorite Menus
* My Tasks
* Pending Approvals
* Notifications
* Quick Actions
* Executive Insight
* Chart Widget

---

### Widget Type

Jenis widget digunakan untuk menentukan pola tampilan.

Contoh:

* CARD
* KPI
* LIST
* TABLE
* CHART
* CALENDAR
* INSIGHT
* ACTION
* WORKFLOW

---

### Widget Permission

Setiap widget dapat dikaitkan dengan permission.

Contoh:

* HR KPI hanya tampil untuk user HR.
* Finance KPI hanya tampil untuk user Finance.
* Executive Insight hanya tampil untuk Management.
* Admin Widget hanya tampil untuk Admin IT.

---

### Widget Configuration

Setiap widget dapat memiliki konfigurasi.

Contoh:

```json
{
  "refresh_interval": 60,
  "show_badge": true,
  "chart_type": "area",
  "limit": 5
}
```

---

### Widget Data Source

Widget dapat mengambil data dari:

* Static metadata
* API endpoint
* Service layer
* KPI Engine
* Workflow Engine
* Notification Engine
* AI Engine

---

## Current Implementation

Model awal:

```txt
DashboardWidget
UserDashboardLayout
```

`DashboardWidget` menyimpan master widget.

`UserDashboardLayout` menyimpan konfigurasi widget per user.

---

## Backend Architecture

```txt
DashboardWidget
        ↓
Widget Service
        ↓
Dashboard API
        ↓
Frontend Registry
        ↓
Vue Component
```

---

## Frontend Architecture

Frontend menggunakan registry.

```txt
widget_type/code
        ↓
Widget Registry
        ↓
Vue Component
```

Contoh:

```txt
favorite_apps → DashboardApplications.vue
favorite_menus → DashboardFavoriteMenus.vue
pending_approvals → DashboardWorkflow.vue
executive_insight → DashboardInsights.vue
```

---

## Database Design

### DashboardWidget

Field utama:

```txt
code
title
description
widget_type
module
is_active
```

Future field:

```txt
component
permission
endpoint
default_width
default_height
default_config
refresh_interval
```

---

### UserDashboardLayout

Field utama:

```txt
tenant
user
widget
position
width
is_visible
```

Future field:

```txt
height
x
y
config
```

---

## API Contract

Endpoint awal:

```txt
GET /api/core/dashboard/widgets/
GET /api/core/dashboard/layout/
POST /api/core/dashboard/layout/
PATCH /api/core/dashboard/layout/{id}/
DELETE /api/core/dashboard/layout/{id}/
```

Future endpoint:

```txt
GET /api/core/dashboard/widgets/available/
POST /api/core/dashboard/widgets/add/
POST /api/core/dashboard/widgets/reorder/
POST /api/core/dashboard/widgets/config/
POST /api/core/dashboard/widgets/reset/
```

---

## Business Rules

* Widget hanya tampil jika `is_active = true`.
* Widget hanya tampil jika user memiliki permission.
* Layout disimpan per tenant dan per user.
* Widget mandatory tidak boleh dihapus oleh user.
* User dapat menyembunyikan widget non-mandatory.
* Admin IT dapat menentukan default widget per role.
* Widget dapat memiliki konfigurasi berbeda per user.

---

## Multi-Tenant Rules

Widget layout bersifat tenant-aware.

Data yang disimpan per user wajib memiliki:

```txt
tenant
user
```

Widget master dapat bersifat tenant-specific agar setiap tenant dapat memiliki konfigurasi dashboard berbeda.

---

## Rendering Flow

```txt
User Login
   ↓
Load Dashboard Layout
   ↓
Load Active Widgets
   ↓
Check Permission
   ↓
Map Widget Code to Component
   ↓
Fetch Widget Data
   ↓
Render Widget
```

---

## Customization Flow

```txt
User opens Dashboard
   ↓
Click Customize
   ↓
Add / Remove / Resize / Move Widget
   ↓
Save Layout
   ↓
Persist UserDashboardLayout
```

---

## Future Roadmap

### Phase 1

* Widget Registry
* Widget API
* User Layout
* Favorite Apps Widget
* Favorite Menus Widget

### Phase 2

* Drag & Drop
* Resize Widget
* Widget Config
* Reset Layout

### Phase 3

* KPI Widget
* Chart Widget
* Workflow Widget
* Notification Widget

### Phase 4

* AI Insight Widget
* Predictive Widget
* Smart Recommendation Widget

---

## References

Dokumen yang berkaitan:

* Dashboard Engine
* Dashboard Workspace
* Authorization
* Workflow Engine
* Notification Engine
* AI Engine

---

## Notes

Widget Engine merupakan bagian penting dari Dashboard Engine.

Setiap widget baru harus didaftarkan ke Widget Registry dan mengikuti standar permission, layout, data source, serta rendering yang telah ditentukan.
