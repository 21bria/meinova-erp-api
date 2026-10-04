# Navigation

Sidebar, menu per modul, Master Hub, dan penyaringan hak akses.

---

## Menu per modul, bukan satu sidebar besar

`app/constants/menus.ts`:

```ts
export const moduleMenus: Record<string, NavMenu[]> = {
  hr: [...],
  administration: [...],
  workflow: [...],
  payroll: [...],
}
```

`AppSidebar.vue` memilih menu dari **`route.path.split('/')[1]`**.

!!! danger "Nama kunci wajib persis sama dengan segmen pertama URL"
    Modul Workflow punya menunya sendiri di sidebar, bukan menumpang Administration. Kuncinya **harus** `workflow` dan halamannya **harus** ada di `app/pages/workflow/`.

    Salah nama kunci = sidebar kosong di seluruh modul itu, tanpa error.

---

## Dua sumber kebenaran yang harus dijaga tetap sama

| Sisi | Isi | Untuk |
|---|---|---|
| `app/constants/menus.ts` (Nuxt) | **sumber kebenaran** daftar menu | apa yang dirender |
| Tabel `Menu` (backend, `seed_menus`) | cerminannya | apa yang bisa **dibatasi per role** |

!!! danger "Menu yang tidak diseed tidak bisa dibatasi"
    Menambah item di Nuxt saja berarti menu itu **selalu terlihat semua role** — dan tidak ada yang memberi tahu.

`seed_menus` mengisi 17 grup + 57 item. Kunci pencocokannya **`route`**, bukan judul — judul berubah jauh lebih sering, dan centang yang sudah disimpan orang tidak boleh hilang gara-gara "Leave" diganti jadi "Cuti".

!!! bug "Kode grup berprefiks `group:`"
    Tanpa itu grup "Masters" dan menu "Masters" menghasilkan kode yang sama, dan `update_or_create` menimpa baris grupnya diam-diam — seed pertama pernah melaporkan "72 baru, 2 diperbarui" di tabel yang **kosong**.

---

## Dua lapis penyaringan di sidebar

`AppSidebar.vue` menyaring **dua kali**:

| Lapis | Sumber | Kosakata |
|---|---|---|
| `isGranted(...)` | wewenang yang dihitung kode (`capabilities`) | `security.manage`, `workflow.configure` |
| `isVisible(...)` | centang `RoleMenuPermission` per tenant | dari `GET /api/accounts/menu-permissions/my/` |

```ts
{ title: 'Security', link: '/administration/security', permission: 'security.manage' }
```

Menu menyebut **nama wewenang**, bukan daftar kode role — supaya mengganti nama role di satu tenant tidak mengharuskan FE dirilis ulang.

Grup yang seluruh itemnya tersaring **ikut dibuang** — judul "Configuration" tanpa satu pun menu di bawahnya cuma membingungkan.

!!! note "Route yang tidak dikenal dianggap boleh"
    Filosofi yang sama dengan `isGranted`: menu yang hilang gara-gara salah ketik jauh lebih sulit dilacak daripada menu yang tampil lalu ditolak API-nya dengan pesan jelas.

!!! danger "Ini BUKAN penjagaan"
    Halamannya tetap bisa dibuka lewat URL. Yang menolak sungguhan tetap API tiap resource.

    Menu access disimpan di `useState` yang bertahan lintas navigasi, jadi **`authStore.clear()` wajib me-`reset()`-nya** — tanpa itu pengguna berikutnya yang login di tab yang sama mewarisi pembatasan milik pengguna sebelumnya.

---

## `visibility_rule` — syarat pola kerja per menu

`always` / `roster_only` / `non_roster_only`.

Ada menu yang benar untuk sebuah role tapi **tidak untuk semua pemegangnya**: Travel Request adalah dokumen **kepulangan dari site**, jadi pegawai kantor pusat tidak punya kepulangan untuk diajukan.

- **Disimpan di baris `RoleMenuPermission`**, bukan di settings — seluruh pengaturan menu di sistem ini sudah per tenant dan bisa disunting dari layar. Diubah lewat **Security → Menu Permissions**
- **Satu baris tanpa syarat sudah cukup membuka menunya** — menambah role harus menambah akses
- Penandanya **dua**: `roster_crew` (jalur lama) **atau** `roster_policy` (jalur Roster Setup). Memeriksa salah satunya saja membuat separuh pegawai site kehilangan menunya
- Grup tidak punya rute, jadi `rule_options`-nya kosong

!!! note "Jangan memecah `EMPLOYEE` jadi dua role hanya demi menu"
    Tiga lapisan harus diduplikasi dan dijaga tetap sama — menu, izin model, cakupan data. Dan pemberian rolenya jadi langkah manual yang **gagal diam-diam** saat orangnya pindah HO↔site: rolenya tertinggal, menunya salah, tanpa satu pun pesan.

    `visibility_rule` membacanya dari penempatan, jadi ikut sendiri.

---

## Ikon: dua kosakata yang harus dijembatani

| Tempat | Gaya |
|---|---|
| `Menu.icon` (sidebar) | Nuxt UI — `i-lucide-clock-3` |
| Beranda | kunci `appRegistry` — `clock-3` |

`menu_catalog._icon()` di backend membuang awalannya.

**Kunci yang tidak dikenal jatuh ke kotak polos tanpa error**, jadi menu baru yang ikonnya belum didaftarkan di `app/registry/app.ts` gagal tanpa suara. 26 ikon pernah ditambahkan sekaligus untuk menutup seluruh isi `MENU_TREE`.

---

## Master Hub

HR dan Payroll memakai pola berkelompok: satu grup "Masters" berisi **satu** entri yang membuka halaman kartu berkategori — bukan daftar tab panjang di sidebar.

| | Lokasi |
|---|---|
| Daftar kartu | `app/registry/master-hub/<modul>.ts` |
| Halaman | `app/pages/<modul>/masters/index.vue` |
| Komponen | `~/features/master-hub` |

Sebagian besar referensi HR tinggal di satu workspace bertab (`/administration/master/hr`). Kartu menautkan langsung ke tabnya lewat `?group=&item=`.

!!! danger "Slug grupnya bukan tebakan"
    `attendance-leave`, `skills-qualification`, `family-emergency`, `employee-separation`, `employee-training`.

    Nilai yang tidak dikenal **diabaikan dan jatuh ke tab pertama** — jadi tautan salah gagal tanpa suara. Periksa terhadap `groups` di `Workspace.vue` setiap kali menambah kartu.

Belum jadi tab di workspace itu: `work-schedules` dan `transport-modes`.

---

## `framework_module` menentukan rute, bukan endpoint

Generator mendorong `router.push("/<framework_module>/create")`. Halaman Nuxt **wajib** ada di `app/pages/<framework_module>/`.

!!! bug "Leave Policy pernah kena"
    `framework_module` `references/hr/leave-policies` sementara halamannya di `/hr/masters/...` — tombol Create dan Edit **404** walau semua berkasnya ada.

    Sudah dipindah ke `hr/leave-policies`; endpoint API-nya tetap `/api/administration/references/hr/leave-policies/`. Keduanya memang tidak harus sama.

---

## Menu pengguna & breadcrumb

- Item **Account** di menu pengguna sidebar menunjuk `/settings/profile`. Sebelumnya item itu **tidak punya tautan sama sekali** — ditekan, menu tertutup, tidak terjadi apa-apa.
- Identitas sidebar dari `auth.user`. Dulu `{ name: 'Meinardus', email: 'admin@meinova.id' }` ditulis **mati** — semua orang yang login melihat nama yang sama, termasuk saat didemokan ke klien.
- `/hr` ditambahkan ke menu `EMPLOYEE`: halamannya memang selalu bisa dibuka, cuma tidak punya jalan masuk dari sidebar — pegawai mendarat di sana lewat breadcrumb lalu **tidak bisa kembali**.

---

## Halaman error

`error.vue` dulu menulis **"404 — Page Not Found"** untuk *semua* error termasuk 500 — halaman yang ada tapi gagal dirender terbaca sebagai halaman yang tidak ada, dan itu mengirim orang mencari sebab di tempat yang salah.

Sekarang kode status dan pesannya ditampilkan apa adanya (pesan exception hanya saat `import.meta.dev`).

---

## Checklist menambah menu

- [ ] Item di `app/constants/menus.ts` — kunci modul = segmen pertama URL
- [ ] Baris di `seed_menus.py` (kalau perlu bisa dibatasi per role)
- [ ] Ikon terdaftar di `app/registry/app.ts` **kalau** menu itu juga jadi pintasan beranda
- [ ] Halaman ada di `app/pages/<framework_module>/`
- [ ] `permission` menyebut nama wewenang, bukan kode role
- [ ] Restart dev server
