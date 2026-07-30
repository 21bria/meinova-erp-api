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

```bash
python manage.py migrate
```

Run development server

```bash
python manage.py runserver
```

---

## Project Structure

```
apps/
config/
core/
media/
static/
requirements/
manage.py
```

---

## API Documentation

Swagger

```
/api/schema/swagger-ui/
```

Redoc

```
/api/schema/redoc/
```

OpenAPI

```
/api/schema/
```

---

## License

Copyright © Meinova.

All Rights Reserved.