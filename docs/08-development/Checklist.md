# Checklist

Halaman rujukan cepat. Kalau kamu cuma sempat membuka satu halaman sebelum commit, buka yang ini.

Latar belakang tiap butir ada di [Pipeline BE → FE](../02-Framework/BE-to-FE-Pipeline.md) dan [Coding Standards](Coding-Standards.md).

---

## Menambah field ke model

- [ ] Field ditambahkan + `makemigrations` + `migrate_schemas`
- [ ] Kalau unik: `UniqueConstraint` + `condition=Q(is_deleted=False)`
- [ ] Field ada di **`serializer.fields`** — kalau tidak, PATCH dibalas **200 lalu nilainya dibuang**
- [ ] Field ada di `Service.FIELDS` (untuk service yang punya daftar eksplisit)
- [ ] Field dideklarasikan di schema dengan `tab=` yang benar
- [ ] `pnpm meinova generate <module>`
- [ ] Buka halamannya di browser

!!! danger "Field employment butuh EMPAT sentuhan"
    Untuk kolom di `EmploymentAssignment` yang muncul di form Employee: serializer mixin, `EmployeeSerializer.fields`, `EmploymentService.FIELDS`, dan schema. `roster_crew` pernah kena — ada di model dan schema, tidak ada di dua sisanya, jadi dropdown-nya tampil kosong walau datanya terisi.

---

## Menambah kolom tabel

- [ ] `table=True` di schema
- [ ] Key-nya **ada di payload API** — kolom lookup dipetakan ke `<field>_name` kecuali `display_key` disebut
- [ ] FK yang jadi kolom ikut `select_related`
- [ ] Regenerate

**Cara memeriksa:** cocokkan `column.*("key")` di `columns.ts` hasil generate dengan payload API sungguhan. Kolom yang keynya tidak ada tampil `-` tanpa error.

---

## Menambah filter

- [ ] `filter=True` **atau** `filter={"group": "quick", "order": 20}` di schema
- [ ] Parameternya terdaftar di **`filterset_fields` / `filterset_class`**
- [ ] Filter lookup punya `lookup_endpoint` (tanpa itu dilewati generator)
- [ ] `depends_on` menyebut setiap field yang dipakai di `lookup_params`
- [ ] Regenerate

---

## Menambah dropdown / lookup

- [ ] `@register_lookup` dengan `name` **unik lintas domain**
- [ ] Registry di-import dari `AppConfig.ready()` — kalau lupa, **404**
- [ ] Path: `/<prefix domain>/lookup/<nama>/`
- [ ] Setiap parameter penyaring terdaftar di `filter_fields`
- [ ] Kalau pakai `autofill`: kuncinya **benar-benar diserialisasi** `serialize()`
- [ ] `DataScopeService.filter` dipasang kalau datanya sensitif
- [ ] Regenerate

---

## Menambah tombol action

- [ ] `@action` dengan `url_path` eksplisit
- [ ] `action.record(...)` di `schema["actions"]`, `endpoint` **URL penuh** + `{id}`
- [ ] `permission` memakai kosakata yang benar — wewenang (`security.manage`) vs izin model (`hr.add_x`)
- [ ] Regenerate

---

## Membuat modul baru

Versi lengkapnya di [Membuat Modul Baru](../02-Framework/Build-A-Module.md). Ringkasnya:

**Backend**

- [ ] Model + migration + reexport
- [ ] Service turunan `BaseMasterService`
- [ ] Serializer menyebut `<relasi>_name` untuk tiap FK yang jadi kolom
- [ ] Schema: `endpoint` eksplisit, `ui`, `fields`
- [ ] ViewSet: **`ServiceWriteMixin` di depan**, `framework_module` unik, `search_fields` cocok model, `filterset_fields` lengkap, `data_scope` terisi
- [ ] URL terdaftar berlapis, urutannya benar
- [ ] `GET /api/framework/schema/<module>/` membalas 200

**Frontend**

- [ ] `pnpm meinova generate <module>`
- [ ] Halaman di **`app/pages/<framework_module>/`**
- [ ] Menu di `app/constants/menus.ts`
- [ ] Restart dev server

**Izin & data**

- [ ] Model ditambahkan ke `GRANTS` di `seed_security_roles`
- [ ] Menu ditambahkan ke `seed_menus`
- [ ] Seed master pendukung

---

## Membuat dokumen berapproval

Tambahan di atas checklist modul:

- [ ] Kolom `status` `TextChoices` (DRAFT/SUBMITTED/APPROVED/REJECTED/CANCELLED/RETURNED)
- [ ] `@action` `submit/` + `withdraw/`
- [ ] `assert_submittable()` dipanggil saat **Submit**, bukan saat penerbitan
- [ ] Callback `@register_completion(module, document_type)` di `workflow_handlers.py`
- [ ] Callback **di-import dari `AppConfig.ready()`** — kalau lupa, Approve jalan tapi status tidak berpindah
- [ ] `registry.register_route()` supaya kotak masuk bisa menautkan
- [ ] `WorkflowDefinition` diseed
- [ ] Deret nomor di `seed_administration --only=numbering`
- [ ] `action.submit()`/`approve()` di schema
- [ ] Efek samping berjalan saat **disetujui**, dan **tidak melempar** di `on_complete`

---

## Sebelum commit

- [ ] Tidak ada `unique=True` polos di turunan `BaseModel`
- [ ] Turunan `BaseReference` memakai `class Meta(BaseReference.Meta)`
- [ ] Tidak ada `fields = "__all__"` pada model berelasi
- [ ] `search_fields` cocok dengan model
- [ ] Label Inggris, help text & komentar Indonesia
- [ ] Komentar menjelaskan **kenapa**, terutama untuk hal yang gagal tanpa suara
- [ ] `python manage.py test apps.hr.tests.roster --keepdb` lolos
- [ ] Migrasi yang menyentuh model hasil rename menyatakan `run_before`
- [ ] `CLAUDE.md` diperbarui kalau ada keputusan desain baru

---

## Sebelum bilang "selesai"

- [ ] **Halamannya dibuka di browser sungguhan** — build lolos bukan bukti
- [ ] Dicoba dengan akun **non-superuser** — penjagaan izin baru terlihat di sana
- [ ] Kolom tabel tidak ada yang "-"
- [ ] Filter benar-benar menyaring (bukan cuma tampil)
- [ ] Dropdown berantai menyempit saat induknya dipilih
- [ ] Error 403/400 muncul sebagai pesan yang bisa dibaca
- [ ] Kalau ada import: **worker Celery direstart**

---

## Menyiapkan tenant baru

Urutan lengkap + jebakannya di [Onboarding](Onboarding.md#4-seed-berurutan). Tiga yang paling sering terlupa:

- [ ] `--only=calendar` — tanpa ini perhitungan hari cuti jatuh ke fallback Senin–Jumat
- [ ] `--only=currency` — tanpa ini tidak ada mata uang dasar, import payroll menolak baris gaji
- [ ] `seed_security_roles` — tanpa ini seluruh sistem read-only kecuali superuser

---

## Membangun ulang data uji

```bash
reset_demo_data → seed_workflows → seed_demo_workforce → seed_roster_demo
→ seed_site_travel_demo → seed_workflow_demo → generate_leave_balances
→ seed_employee_action_demo → seed_demo_attendance
```

- [ ] `seed_roster_demo` **sebelum** `seed_site_travel_demo`
- [ ] `seed_demo_attendance` **paling akhir**
