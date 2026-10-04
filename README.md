# Meinova ERP API

Modern Enterprise Resource Planning (ERP) REST API built with Django, Django REST Framework, PostgreSQL, and JWT Authentication.

---

## Features

- Multi-Tenant Architecture
- JWT Authentication
- Role & Permission Management
- Organization Management
- Human Resource Management (HRM)
- Payroll Management
- Supply Chain Management (SCM)
- Finance & Accounting
- Workflow Engine
- Approval System
- RESTful API
- OpenAPI / Swagger Documentation
- File Upload Management
- Audit Logging
- Background Tasks
- Docker Ready

---

## Technology Stack

- Python 3.13+
- Django
- Django REST Framework
- PostgreSQL
- django-tenants
- Simple JWT
- Celery
- Redis
- Docker
- Nginx

---

## Requirements

- Python 3.13+
- PostgreSQL 16+
- Redis
- Git

---

## Installation

Clone repository

```bash
git clone https://github.com/21bria/meinova-erp-api.git
cd meinova-erp-api
```

Create virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies

```bash
pip install -r requirements.txt
```

Copy environment

```bash
cp .env.example .env
```

Run migration

> This project uses **django-tenants**. Plain `python manage.py migrate` is
> not enough — schemas are migrated separately.

```bash
python manage.py migrate_schemas --shared       # SHARED_APPS → public schema
python manage.py migrate_schemas                # all tenant schemas
python manage.py migrate_schemas --schema=demo  # a single tenant
```

Run development server

```bash
python manage.py runserver
celery -A config worker -l info   # separate terminal
```

Seeding a new tenant takes a specific order — see
[`docs/08-development/Onboarding.md`](docs/08-development/Onboarding.md).

---

## Project Structure

```
apps/
  accounts/        RBAC: model permissions, menu access, data scoping
  administration/  organization, references, calendar, numbering, audit
  core/            base models, base services, response envelope
  framework/       schema-driven UI engine, lookup, generic import
  hr/              employees, attendance, leave, roster, travel, recruitment
  imports/  uploads/
  payroll/         models + seeds complete, API partial
  tenants/         django-tenants Client / Domain
  workflow/        generic approval engine
  assets/ finance/ reports/ scm/   ← registered but empty
config/
docs/
media/
manage.py
```

---

## Documentation

```bash
pip install mkdocs mkdocs-material
mkdocs serve -a 127.0.0.1:8001
```

Start at [`docs/index.md`](docs/index.md). The one page every new developer
should read first is
[`docs/02-Framework/BE-to-FE-Pipeline.md`](docs/02-Framework/BE-to-FE-Pipeline.md) —
the frontend is generated from backend schema, so changing a model without
regenerating the module silently changes nothing on screen.

---

## API Documentation

| | URL |
|---|---|
| Swagger UI | `/api/docs/` |
| OpenAPI schema | `/api/schema/` |

Requests are tenant-scoped by hostname, so use the tenant domain:
`http://demo.localhost:8000/api/docs/`

---

## License

Copyright © Meinova.

All Rights Reserved.