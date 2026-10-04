# ERP Knowledge Base

Berkas ini hanya penunjuk arah saat membaca repo lewat file browser.
**Halaman depan dokumentasi yang sebenarnya ada di [`index.md`](index.md)** — itu yang dirender mkdocs.

## Menjalankan

```bash
pip install mkdocs mkdocs-material pymdown-extensions
mkdocs serve -a 127.0.0.1:8001
```

## Struktur

```
docs/
├── index.md                 ← mulai dari sini
├── 00-overview/             visi, roadmap, changelog
├── 01-architecture/         multi-tenant, auth, engine (sebagian blueprint)
├── 02-Framework/            ⭐ inti untuk developer
│   ├── BE-to-FE-Pipeline.md    ⭐ wajib dibaca
│   ├── Build-A-Module.md       tutorial end-to-end
│   ├── Request-Lifecycle.md
│   ├── Base-Classes.md · Schema.md · Lookup.md · Permission.md · Generator.md
├── 03-modules/
│   └── Module-Registry.md      ⭐ status semua modul
├── 04-ui-ux/  05-api/  06-database/  07-deployment/
├── 08-development/
│   └── Onboarding.md           ⭐ hari pertama
└── 09-business-flows/       ⭐ alur bisnis
    ├── Overview.md · Document-Approval.md
    └── Leave-Request.md · Travel-Request.md · Roster-Management.md · Employee-Action.md
```

## Tiga jalur baca

| Kamu | Baca |
|---|---|
| BE developer baru | Onboarding → Request-Lifecycle → BE-to-FE-Pipeline → Build-A-Module |
| FE developer baru | Onboarding → BE-to-FE-Pipeline → Schema → Generator |
| Analis / PM / QA | 09-business-flows/Overview → empat alur → Module-Registry |

## Catatan

Sebagian folder di `03-modules/` (`crm`, `fleet`, `fuel`, `mining`, `safety`, …) adalah **blueprint produk — belum ada kodenya**. Status yang berlaku hari ini ada di [Module Registry](03-modules/Module-Registry.md).
