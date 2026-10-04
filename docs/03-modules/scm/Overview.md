# Supply Chain Management (SCM) Module

!!! danger "📋 Blueprint — belum ada kodenya"
    App `scm` terdaftar di `INSTALLED_APPS` tapi **isinya kosong**. Di beranda ia bertanda `COMING_SOON`; pintasan `/scm/purchase-requests` yang lama sudah **ditarik** karena menghasilkan `[Vue Router warn] No match found` di beranda setiap kali dimuat.

    Halaman ini rencana produk, **bukan rujukan implementasi**. Status yang berlaku hari ini: [Module Registry](../Module-Registry.md), dan langkah membangun modul baru di [Build A Module](../../02-Framework/Build-A-Module.md).

---



> Version: 1.0
> Status: Active
> Module: Supply Chain Management
> Priority: Critical

---

## Purpose

Supply Chain Management (SCM) merupakan modul inti pada platform ERP yang bertanggung jawab untuk mengelola seluruh proses pengadaan barang dan jasa, pergerakan material, persediaan, pergudangan, serta distribusi dalam satu sistem yang terintegrasi.

SCM menjadi penghubung antara kebutuhan operasional, pengadaan, inventori, keuangan, proyek, dan aset sehingga seluruh rantai pasok perusahaan dapat dipantau secara real-time.

---

## Scope

Modul SCM mencakup:

* Procurement
* Purchase Request (PR)
* Purchase Order (PO)
* Vendor Management
* Request for Quotation (RFQ)
* Goods Receipt (GR)
* Goods Issue (GI)
* Warehouse Management
* Material Transfer
* Inventory Integration
* Logistics & Delivery
* Contract Management
* Workflow & Approval
* Dashboard & Analytics

---

# Objectives

Modul SCM dikembangkan untuk:

* Mengelola proses pengadaan secara terstandarisasi.
* Mengurangi waktu proses pembelian.
* Mengontrol persediaan barang.
* Mengoptimalkan hubungan dengan vendor.
* Menyediakan visibilitas penuh terhadap rantai pasok.
* Mengintegrasikan pengadaan dengan Finance, Inventory, Project, dan Asset.

---

# Supply Chain Lifecycle

Seluruh proses SCM mengikuti siklus berikut:

```text id="e91vzf"
Purchase Request
        ↓
Approval
        ↓
Request for Quotation
        ↓
Purchase Order
        ↓
Goods Receipt
        ↓
Warehouse
        ↓
Inventory
        ↓
Payment (Finance)
```

---

# Main Features

SCM terdiri dari beberapa sub-modul:

* Vendor Management
* Purchase Request
* Request for Quotation
* Purchase Order
* Goods Receipt
* Warehouse
* Material Transfer
* Contract Management
* Logistics
* Procurement Reports

Setiap sub-modul memiliki dokumentasi tersendiri.

---

# Integration

SCM terintegrasi dengan:

* Organization
* Finance
* Inventory
* Asset
* Project
* Maintenance
* Fleet
* Mining
* Workflow Engine
* Task Engine
* Notification Engine
* Dashboard Engine
* Search Engine
* AI Engine

---

# Dashboard

Dashboard SCM menyediakan informasi seperti:

* Open Purchase Request
* Open Purchase Order
* Vendor Performance
* Pending Goods Receipt
* Procurement Cycle Time
* Material Consumption
* Warehouse Summary
* Inventory Movement
* Contract Expiry

---

# AI Capabilities

AI dapat membantu SCM melalui:

* Procurement Summary
* Vendor Recommendation
* Purchase Forecast
* Stock Replenishment Recommendation
* Slow Moving Analysis
* Procurement Cost Analysis
* Supplier Performance Insight
* Contract Expiry Reminder

---

# Future Roadmap

Pengembangan selanjutnya meliputi:

* E-Procurement Portal
* Vendor Self Service
* Vendor Performance Scorecard
* Electronic Tender
* Barcode & QR Integration
* RFID Warehouse
* Shipment Tracking
* AI Procurement Assistant
* Demand Forecasting

---

## References

Dokumen terkait:

* Vendor Management
* Purchase Request
* Request for Quotation
* Purchase Order
* Goods Receipt
* Warehouse
* Material Transfer
* Contract Management
* Dashboard
* API
* Database

---

## Notes

Overview ini memberikan gambaran umum mengenai modul Supply Chain Management. Detail implementasi setiap fitur dijelaskan pada dokumen sub-modul yang terpisah.
