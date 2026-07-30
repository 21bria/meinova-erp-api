# Organization Module

## Overview

Organization merupakan pondasi utama dari seluruh Meinova ERP.

Semua modul akan menggunakan struktur Organization sebagai referensi utama.

Contohnya:

- Human Resource
- Payroll
- Inventory
- Asset
- Maintenance
- Purchasing
- Finance
- CRM
- Mining

Organization mendefinisikan:

- Struktur perusahaan
- Lokasi operasional
- Unit kerja
- Jabatan
- Hubungan pelaporan

Organization **tidak menyimpan proses bisnis**, tetapi hanya menjadi master data yang digunakan seluruh sistem.

---

# Relationship with HR

Organization hanya menyimpan struktur organisasi.

Employee berada pada module HR dan mereferensikan struktur Organization.

```
Company
    │
    ├── Branch
    │
    ├── Site
    │
    ├── Division
    │
    ├── Department
    │
    ├── Section
    │
    └── Position
             │
             ▼
        HR Employee
```

Setiap Employee akan memilih:

- Company
- Branch
- Site
- Division
- Department
- Section
- Position
- Reports To

Organization tidak menyimpan data Employee.

Organization hanya menyediakan master data yang digunakan oleh HR, Payroll, Inventory, Finance, Asset, Maintenance, CRM, dan Mining.

## Notes
Dokumen ini akan diperbarui seiring pengembangan fitur.
