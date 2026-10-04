# Pull Request

Apa yang harus ada di sebuah PR supaya bisa direview dengan sungguh-sungguh.

Yang **diperiksa** reviewer ada di [Code Review](Code-Review.md). Aturan branch dan commit di [Git Workflow](Git-Workflow.md).

---

## Template deskripsi

```markdown
## Apa
<satu-dua kalimat>

## Kenapa
<masalah yang diselesaikan — kalau ini bug, apa gejalanya di layar>

## Cara memverifikasi
1. `python manage.py tenant_command <seed> --schema=demo`
2. Buka `/hr/...`
3. <yang seharusnya terlihat>

## Menyentuh repo lain?
- [ ] Tidak
- [ ] Ya → meinova-erp#<PR> / branch `feat/...`
      Module yang diregenerate: `hr/leave`, `hr/employees`

## Migrasi
- [ ] Tidak ada
- [ ] Ada → `hr/0042_add_vehicle.py`
      Butuh `migrate_schemas` (semua tenant)

## Seed yang harus dijalankan setelah deploy
- [ ] Tidak ada
- [ ] `tenant_command seed_menus`, `seed_security_roles`

## Checklist
- [ ] Halamannya dibuka di browser
- [ ] Dicoba dengan akun non-superuser
- [ ] Test lolos
- [ ] CLAUDE.md diperbarui (kalau ada keputusan desain baru)
```

---

## Kenapa empat bagian terakhir itu wajib

Bukan formalitas — keempatnya adalah hal yang **tidak terlihat dari diff** dan menyebabkan kegagalan diam kalau terlewat.

### "Menyentuh repo lain?"

Perubahan schema tanpa regenerate FE = tidak ada yang berubah di layar, **tanpa error**. Tidak ada tooling yang mengaitkan dua repo; baris ini satu-satunya penanda.

Backend di-merge **lebih dulu** — generator butuh endpoint schema-nya hidup.

### "Migrasi"

`migrate_schemas` menyentuh **setiap** schema tenant. Untuk tenant berjumlah puluhan, itu bukan operasi sepele dan orang yang deploy perlu tahu sebelumnya.

Dan migrasi yang menyentuh model hasil rename wajib menyatakan `run_before` — kalau tidak, **penyediaan tenant baru gagal**, dan itu baru ketahuan berminggu-minggu kemudian saat ada klien baru.

### "Seed yang harus dijalankan"

Modul baru yang menunya belum diseed **tidak bisa dibatasi per role** — ia selalu terlihat semua orang. Model baru yang belum masuk `GRANTS` membuat tombol Save-nya **403 setelah form diisi**.

Keduanya tidak terlihat di diff, dan keduanya baru terasa di produksi.

### "Dicoba dengan akun non-superuser"

Superuser melewati hampir semua penjagaan di sistem ini — `ModelPermission`, `EmployeeActionPolicy`, `EmployeeDataPolicy`, dan cakupan data. Menguji sebagai superuser berarti **tidak menguji satu pun lapis izin**.

Akun uji: `demo.hrmanager`, `demo.hostaff`, dst. Password: nilai `DEMO_PASSWORD` yang dipakai saat seed (`<DEMO_PASSWORD>`).

---

## Ukuran

Target: **bisa direview sekali duduk.**

PR yang menyentuh 40 file di 6 modul tidak akan direview dengan sungguh-sungguh — dan review yang tidak sungguh-sungguh lebih buruk daripada tidak ada, karena ia memberi rasa aman palsu.

Kalau besar, pisahkan:

| Perubahan | Pecahan |
|---|---|
| Modul baru | (1) model + migration → (2) service + API → (3) schema + generate → (4) seed izin & menu |
| Refactor lintas modul | (1) tambahkan yang baru berdampingan → (2) pindahkan pemanggil → (3) hapus yang lama |

!!! tip "Pisahkan hasil generate ke commit tersendiri"
    Regenerate satu modul menghasilkan diff ratusan baris yang menyembunyikan perubahan sungguhan. Satu commit berisi perubahan schema BE, satu commit berisi hasil generate FE — reviewer bisa melewati yang kedua.

---

## Jangan minta review sebelum

- [ ] Kamu sendiri sudah membuka halamannya di browser
- [ ] `.env` tidak ikut ter-commit
- [ ] `makemigrations --check --dry-run` bersih
- [ ] [Checklist](Checklist.md) sudah dilewati

Reviewer yang menemukan kolom "-" di baris pertama akan berhenti membaca sisanya, dan siklus reviewnya jadi dua kali lebih panjang.

---

## Keadaan hari ini

Belum ada PR yang pernah dibuat (2 commit, 1 branch, tanpa CI). Template di atas berlaku begitu ada orang kedua — dan sementara itu berguna sebagai format catatan perubahan untuk diri sendiri.

Kalau nanti dipasang, template ini masuk `.github/pull_request_template.md`.
