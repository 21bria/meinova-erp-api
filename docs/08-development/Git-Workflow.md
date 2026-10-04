# Git Workflow

!!! warning "Keadaan sebenarnya hari ini"
    Repo ini punya **2 commit** dan **1 branch** (`main`). Belum ada proses git yang berjalan.

    Halaman ini menetapkan alur yang **akan** dipakai begitu ada lebih dari satu orang menyentuh repo — ditulis sekarang supaya tidak diputuskan tergesa-gesa saat orang kedua bergabung.

---

## Dua repo, satu perubahan

Ini yang membuat alur di sini berbeda dari proyek biasa.

Perubahan schema **selalu** menyentuh dua repo:

```
backend-erp     : model + service + schema
meinova-erp     : hasil pnpm meinova generate
```

| Aturan | Alasan |
|---|---|
| Commit BE dan FE **dirujuk silang** di pesan commit | tidak ada tooling yang mengaitkan keduanya |
| Backend **di-merge lebih dulu** | endpoint schema harus ada sebelum generator bisa jalan |
| Hasil generate **di-commit**, tidak di-`gitignore` | reviewer perlu melihat apa yang berubah di layar, dan build tidak menjalankan generator |

!!! danger "Backend yang di-deploy tanpa FE diregenerate = fitur yang tidak terlihat"
    Tidak ada error, tidak ada indikator versi di UI. Layarnya cuma tetap memakai definisi lama.

---

## Branch

```
main                          ← selalu bisa di-deploy
  feat/hr-vehicle-master
  fix/leave-balance-sync
  chore/docs-restructure
```

| Prefix | Untuk |
|---|---|
| `feat/` | fitur baru |
| `fix/` | perbaikan bug |
| `refactor/` | tanpa perubahan perilaku |
| `chore/` | seed, docs, dependency, tooling |
| `migrate/` | migrasi data yang berdiri sendiri |

Satu branch = satu perubahan yang bisa direview sekali duduk. Branch yang menyentuh 40 file di 6 modul tidak akan direview dengan sungguh-sungguh.

---

## Pesan commit

```
<tipe>(<scope>): <ringkasan imperatif>

<kenapa perubahannya, bukan apa yang diubah>

Refs: meinova-erp@<sha> (kalau menyentuh FE)
```

Contoh:

```
fix(hr): hitung travel sekali per putaran, bukan dua kali

apply_cycle_pattern memakai work + off + travel * 2 saat menurunkan
start_date dari jangkar crew, jadi tanggal mulai otomatis mendarat di
tanggal yang bukan awal siklus crew mana pun — meleset `travel` hari
tiap putaran dan menumpuk sepanjang tahun.

Hanya kena dokumen baru yang start_date-nya dikosongkan.
```

Ringkasan menjawab **apa**, badan menjawab **kenapa** dan **apa yang gagal sebelumnya**. Konsisten dengan gaya komentar di codebase ini.

---

## Yang tidak boleh masuk commit

- `.env` (sudah di `.gitignore` — periksa sebelum `git add -A`)
- `venv/`, `__pycache__/`, `node_modules/`
- `media/` — file upload
- `test.log`, `cek_mesin_finger.txt`, dan berkas coretan sejenis di root
- Berkas hasil generate FE **yang tidak sengaja** ikut — regenerate satu modul tidak boleh membawa diff modul lain

!!! warning "Regenerate menghasilkan diff besar yang menyembunyikan perubahan sungguhan"
    Pisahkan jadi dua commit: satu berisi perubahan schema BE, satu berisi hasil generate FE. Reviewer bisa melewati yang kedua.

---

## Migrasi

- **Satu branch, satu migrasi per app** kalau bisa. Dua migrasi di app yang sama dari dua branch berbeda akan konflik pada `dependencies`.
- **Jangan menyunting migrasi yang sudah di-merge.** Buat migrasi baru.
- **Migrasi yang menyentuh model hasil rename wajib `run_before`** — lihat [Coding Standards](Coding-Standards.md#migrasi).
- Migrasi data yang berat sebaiknya berdiri sendiri di branch `migrate/`, supaya bisa dijalankan dan dipantau terpisah.

---

## Konflik yang khas di repo ini

| Berkas | Kenapa sering konflik | Cara aman |
|---|---|---|
| `apps/<app>/models/__init__.py` | semua orang menambah reexport | tambahkan di urutan alfabet |
| `apps/<app>/api/urls.py` | pendaftaran router | perhatikan **urutannya**, jangan asal ambil keduanya |
| `seed_menus.py`, `APP_CATALOG`, `HOME_WIDGETS` | daftar yang bertambah | ambil keduanya, periksa kode duplikat |
| `mkdocs.yml` nav | | ambil keduanya |
| Berkas hasil generate FE | | **jangan merge manual — regenerate** |

Untuk yang terakhir: hasil generate adalah keluaran, bukan sumber. Resolusi yang benar adalah `git checkout --theirs` lalu jalankan generator lagi.

---

## Sebelum push

- [ ] `python manage.py test apps.hr.tests.roster --keepdb` lolos
- [ ] `python manage.py makemigrations --check --dry-run` tidak menghasilkan migrasi baru yang belum di-commit
- [ ] `.env` tidak ikut
- [ ] Halamannya sudah dibuka di browser
- [ ] Checklist di [Checklist](Checklist.md) sudah dilewati

---

## Yang belum ada

- **CI** — tidak ada `.github/`. Kalau dipasang, minimal: `migrate_schemas --shared` + `python manage.py test --keepdb` di setiap push.
- **Branch protection** pada `main`.
- **Pre-commit hook.** Kandidat pertamanya bukan formatter, melainkan pemeriksa `.env` dan `makemigrations --check`.
