# Future Roadmap

Organization Module Roadmap

Status:
- ✅ Implemented
- 🚧 In Progress
- ⏳ Planned
- 💡 Idea

---

# Phase 1 — Foundation

Status: ✅

- Company
- Branch
- Site
- Division
- Department
- Section
- Position
- Cost Center

---

# Phase 2 — Organization Management

Status: 🚧

- Organization Tree
- Drag & Drop Organization
- Position Hierarchy
- Reports To Hierarchy
- Organization Chart

---

# Phase 3 — Employee Integration

Status: ⏳

- Position Assignment
- Position History
- Department Transfer
- Promotion
- Demotion
- Rotation
- Acting Position

---

# Phase 4 — Workflow

Status: ⏳

- Approval berdasarkan Reports To
- Escalation
- Multi Level Approval
- Delegation
- Substitute Approver

---

# Phase 5 — Enterprise Features

Status: 💡

- Matrix Organization
- Multiple Reporting Line
- Organization Versioning
- Effective Date Structure
- Headcount Planning
- Vacancy Planning
- Budget per Position

---

# Phase 6 — Mining Integration

Status: 💡

Site
    │
    └── IUP
            │
            └── Prospect Area
                    │
                    └── Pit
                            │
                            └── Loading Point

Organization hanya sampai Site.

Mining memperluas struktur tersebut tanpa mengubah Organization.

---

# Phase 7 — Dashboard

Status: 💡

Organization Summary

- Total Company
- Total Branch
- Total Site
- Total Department
- Total Position
- Organization Chart
- Headcount by Site
- Headcount by Department

---

# Phase 8 — API

Status: 💡

Organization Tree API

GET /organization/tree/

Position Hierarchy API

GET /organization/positions/tree/

Organization Chart API

GET /organization/chart/

---

# Notes

Organization harus tetap menjadi Generic Module.

Jangan memasukkan konsep Mining,
Hospital,
Manufacturing,
atau industri tertentu ke dalam module ini.

Semua industri harus melakukan extension melalui Site.