# Branching

Strategi branch: **trunk-based** dengan branch pendek berumur harian, bukan GitFlow.

Latar belakang dan aturan commit-nya di [Git Workflow](Git-Workflow.md).

---

## Kenapa bukan GitFlow

GitFlow (`develop` + `release/*` + `hotfix/*`) masuk akal untuk produk yang dirilis berkala ke banyak pelanggan sekaligus dengan versi yang harus dipelihara berdampingan.

Sistem ini tidak begitu:

- **Dua repo yang harus dirilis bersamaan.** Menambah cabang panjang di keduanya berarti empat kombinasi yang harus dijaga sinkron.
- **Frontend digenerate dari backend.** Branch FE yang hidup lama akan membawa hasil generate dari schema yang sudah tidak ada.
- **Belum ada CI.** Cabang panjang tanpa integrasi otomatis adalah cara paling pasti menumpuk konflik yang tidak bisa direview.

---

## Struktur

```
main                     ← selalu bisa di-deploy
 ├── feat/hr-vehicle-master
 ├── fix/leave-balance-sync
 └── chore/docs-restructure
```

Satu tingkat. Tidak ada `develop`.

| Prefix | Untuk |
|---|---|
| `feat/` | fitur baru |
| `fix/` | perbaikan bug |
| `refactor/` | tanpa perubahan perilaku |
| `chore/` | seed, docs, dependency, tooling |
| `migrate/` | migrasi data yang berdiri sendiri |

Nama branch memakai kebab-case dan menyebut **domainnya**: `feat/hr-vehicle-master`, bukan `feat/new-feature`.

---

## Umur branch

**Target: kurang dari 2 hari.** Kalau lebih lama, biasanya scope-nya terlalu besar dan sebaiknya dipecah.

Pemecahan yang biasanya bisa dilakukan:

| Perubahan besar | Bisa dipecah jadi |
|---|---|
| Modul baru lengkap | (1) model + migration, (2) service + API, (3) schema + generate FE, (4) seed izin & menu |
| Refactor lintas modul | (1) tambahkan yang baru berdampingan, (2) pindahkan pemanggil satu per satu, (3) hapus yang lama |
| Perbaikan yang menyentuh 100 modul FE | pasang perbaikannya di `framework/` — **tidak perlu menyentuh 100 modul sama sekali** |

Yang terakhir bukan trik: itu memang cara yang benar di repo ini. Lihat [Generator](../02-Framework/Generator.md#aturan-memilih-tempat-perbaikan).

---

## Sinkronisasi dua repo

Branch di BE dan FE untuk satu perubahan sebaiknya **bernama sama**:

```
backend-erp   : feat/hr-vehicle-master
meinova-erp   : feat/hr-vehicle-master
```

Tidak ada tooling yang mengaitkannya — nama yang sama adalah satu-satunya penanda.

Urutan merge: **backend dulu**, karena generator butuh endpoint schema-nya hidup.

---

## Rebase, bukan merge commit

```bash
git fetch origin
git rebase origin/main
```

Riwayat linear membuat `git log` bisa dibaca, dan `git bisect` berguna. Merge commit dari branch pendek cuma menambah derau.

**Pengecualian:** jangan rebase branch yang sudah di-push dan sedang direview orang lain.

---

## Migrasi menentukan urutan merge

Dua branch yang sama-sama menambah migrasi di app yang sama **akan konflik** pada `dependencies`.

- Kalau tahu sedang ada branch lain yang menyentuh app yang sama, merge yang duluan selesai lebih dulu lalu rebase yang kedua
- Rebase migrasi = **ganti nomor & `dependencies`-nya**, bukan resolve konflik teks
- Migrasi data yang berat berdiri sendiri di `migrate/`, supaya bisa dijalankan dan dipantau terpisah dari deploy fitur

---

## Hotfix

Tidak ada cabang khusus. Hotfix adalah `fix/` biasa yang di-merge duluan.

Yang membedakan cuma urgensinya, dan itu bukan sesuatu yang perlu dinyatakan lewat struktur branch.

---

## Yang perlu ditambahkan nanti

- **Branch protection** pada `main`: butuh review, butuh CI hijau
- **Auto-delete branch** setelah merge
- **CI** yang menjalankan test — tanpa ini, "selalu bisa di-deploy" pada `main` hanya janji lisan
