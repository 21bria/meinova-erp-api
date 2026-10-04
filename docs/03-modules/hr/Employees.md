# Employee Master

`framework_module = "hr/employees"` · workspace bertab · modul dengan field terbanyak di sistem ini.

---

## Bentuk data

`Employee` hanya identitas. Perilakunya ditentukan empat model penempatan — lihat [Database](Database.md#employee-dan-empat-penempatannya).

Tab di kartu pegawai: General · Organization · Employment · Payroll · Bank · Family · Education · Documents · Medical · **History**.

!!! note "Employee Action tidak punya tab, dan itu disengaja"
    Kartu pegawai menjawab **"keadaannya sekarang apa"**. Employee Action adalah dokumen berjalan dengan status dan alurnya sendiri, dan sudah punya modulnya.

    Yang tersisa di kartu cuma pintu masuknya: tombol **Actions** (`action.create_resource`) yang membuka form dokumen itu dengan pegawainya sudah terisi dan **tidak bisa dipilih ulang**. Dari menu global, form yang sama tetap meminta pegawainya dipilih — satu deklarasi field, dua pintu masuk.

    Hasilnya terbaca di tab **History**.

---

## Nomor pegawai otomatis

`<KODE COMPANY><YY><4 digit>` — `KW260001`, `IMM260001`. Per company per tahun, lewat `NumberingSequence`/`DocumentSeries`.

**Bukan** `Employee.objects.count() + 1` dan bukan pk: keduanya mengulang nomor begitu ada baris yang dihapus, dan pk tidak pernah reset per tahun.

- Baris deret per company dibuat sekali saat pertama dipakai (`prefix=Company.code`, separator kosong, padding 4, `year_digits=2`, `reset_yearly`), sesudah itu bisa disunting dari layar Numbering
- `NumberingSequence.year_digits` ditambahkan untuk ini — bawaannya tetap 4 digit, jadi deret dokumen lain tidak berubah

### Kolomnya dikunci, bukan disembunyikan

Sempat disembunyikan selama Auto menyala, dan hasilnya **kolom yang paling dicari orang di form pegawai baru tidak ada di layar sama sekali**.

Sekarang `readonly_when`. Field Company membawa `autofill={"employee_number": "next_employee_number"}` dan `CompanyLookup.serialize()` mengirim `EmployeeNumberService.preview()` — memilih Company langsung memperlihatkan nomor yang akan terbit.

!!! warning "Angka preview adalah tebakan"
    Ia tidak mengunci, tidak menaikkan penghitung, dan tidak membuat baris master. Yang benar-benar terbit dialokasikan `next_number()` saat Simpan.

    Karena itu kolomnya **dikunci** selama Auto menyala — angka yang bisa diketik ulang lalu diabaikan server lebih buruk daripada tidak ditampilkan.

**Hanya saat create.** `auto_generate_employee_number` adalah penanda write-only yang di-pop di serializer/service, ditolak saat update, dan tidak pernah dihitung ulang — nomor yang sudah terbit sudah tercetak di kontrak dan terdaftar di mesin absensi.

Auto dimatikan → nomor diketik tangan, keunikannya diperiksa **di serializer** dengan pesan yang **menyebut siapa pemakainya**. Tanpa itu tabrakan muncul sebagai `Constraint uniq_active_employee_number is violated` — kalimat yang tidak menempel di kolom mana pun.

---

## Menambah kolom employment butuh EMPAT sentuhan

!!! danger "Yang kelewat gagal tanpa suara"
    1. Field di `serializers/mixins/employment.py` (`source="employment.<kolom>"`)
    2. Namanya di `fields` milik `EmployeeSerializer` — **tidak terdaftar = PATCH balas 200 lalu nilainya dibuang**
    3. `EmploymentService.FIELDS`
    4. Schema di `schema/fields/employment.py`

    `roster_crew` dan `roster_start_override` pernah kena persis ini — ada di model dan di schema, tidak ada di dua sentuhan sisanya, jadi **dropdown-nya tampil kosong walau datanya terisi** dan tidak ada seorang pun bisa memilih crew dari form Employee.

`EmployeeService` mem-pop dict `employment` dan `setattr` apa adanya, jadi **kunci dict itu nama kolom model** — bukan nama field serializer.

!!! note "Response PATCH mengembalikan nilai employment yang basi"
    Dirakit dari instance **sebelum** `EmploymentService.save()`. Berlaku untuk semua kolom employment. GET berikutnya sudah benar, dan FE memang refetch setelah simpan.

---

## Tiga tab Employment, bukan satu

Dulu delapan belas kolom dalam satu tumpukan, semuanya boleh diketik ulang kapan saja.

| Tab | Isi |
|---|---|
| `employment` | Current Employment |
| `contract` | Contract & Probation |
| `work_arrangement` | pola kerja, roster, kalender |

Daftar fieldnya **diturunkan dari `tab=`** lewat `employment_tab_fields()`, bukan didaftar ulang di `tabs.py` — dua daftar yang harus tetap sama cepat atau lambat berbeda, dan field yang hilang dari daftar tab **tidak muncul di form tanpa satu pun pesan**.

### Kolom terkunci ada di service, bukan cuma di tampilan

`EmploymentService.PROTECTED_FIELDS` — jenis, status, kontrak, probation, confirmation, terminasi.

| Operasi | Perilaku |
|---|---|
| **Create** | bebas — pegawai baru boleh membawa keadaan awalnya |
| **Update** | ditolak, dengan pesan menyebut Employee Action mana yang harus dipakai |
| `save(via_action=True)` | melewatinya — **hanya** `EmployeeActionService.apply()` yang boleh |

!!! danger "Diperiksa dengan MEMBANDINGKAN NILAI, bukan melihat kunci mana yang dikirim"
    Form mengirim seluruh isi tab apa adanya. Menolak setiap kiriman yang **memuat** kunci terkunci membuat menyimpan Job Location pun ditolak dengan alasan kontrak.

**Sengaja tidak terkunci:** `join_date`, `employee_group`, `job_location`, `point_of_hire`, dan seluruh work arrangement. Itu koreksi data yang wajar.

---

## Work Schedule vs Roster Crew — dua field yang paling sering ketuker

Keduanya sama-sama "pola kerja". Aturannya: **Roster Crew yang menentukan**, Work Schedule mengikutinya — `EmploymentAssignment.clean()` menolak kalau berbeda.

Karena itu Roster Crew ditaruh **lebih dulu** di form (`order=128` vs `130`) dan membawa `autofill={"work_schedule": "work_schedule"}`; `RosterCrewLookup.serialize()` ikut mengirim `work_schedule` supaya autofill-nya ada isinya.

| Pegawai | Cara mengisi |
|---|---|
| HO/kantor | Roster Crew **dikosongkan**, Work Schedule dipilih sendiri (Regular 5 Days) |
| Site | pilih crew, polanya terisi otomatis |

---

## Kolom kontrak tampil bersyarat

`visible_when` pada `employment_type_requires_contract`. Tiga bagian yang harus lengkap:

1. `EmploymentTypeLookup.serialize()` mengirim `requires_contract`
2. field Employment Type membawa `autofill`
3. serializer Employee ikut mengirim field yang sama — supaya nilainya benar saat form **dimuat**, bukan cuma setelah diganti

Cabut salah satunya, dan kolomnya benar di satu keadaan lalu salah di keadaan lain.

**`EmploymentType.requires_contract` yang menentukan, bukan kodenya** — tenant yang menamai masternya sendiri tidak boleh kehilangan kolom kontrak hanya karena kodenya bukan `CONT`.

---

## Saldo cuti terbit sendiri

`EmploymentService.sync_leave_balances`, dipicu perubahan **Join Date / Employee Group / Employment Type** — tiga kolom yang menentukan jatah.

Hanya tahun berjalan dan tahun depan yang disentuh: saldo yang sudah terpakai dan ditutup tidak boleh berubah gara-gara koreksi data induk hari ini.

Kegagalannya `logger.exception` dan **tidak** menggagalkan penyimpanan pegawai — master cuti yang belum diseed adalah keadaan yang sah.

---

## Kerahasiaan: tiga jalur, menutup satu tidak menutup dua lainnya

`EmployeeDataPolicy` kelompok `field_*` mengatur **keadaan sekarang**, bukan riwayat.

| Jalur | Cara menutupnya |
|---|---|
| **Serializer** | `_mask_hidden` **membuang** field dari payload — bukan mengosongkan jadi `null`, karena kolom kosong dan kolom yang belum diisi terbaca sama |
| **Endpoint sub-resource** | tab Payroll/Bank/Family/Medical/Documents masing-masing endpoint tersendiri → `EmployeeDataSubjectMixin` di `filter_queryset()` |
| **Export CSV** | `resolve_export_value` membaca **instance**, jadi masking serializer tidak menyentuhnya sama sekali |

!!! warning "Jebakan di serializer"
    `to_representation` menulis ulang kolom payroll dari baris `is_current` **setelah** masking — nilainya harus disaring lagi di sana.

!!! warning "Di CSV, kolomnya dibuang seluruhnya"
    Bukan dikosongkan per baris: CSV yang sebagian selnya terisi justru **membocorkan polanya** — pembacanya tahu persis pegawai mana yang datanya dibatasi.

Seed bawaan: `EDP-PAYROLL` (ybs + atasan + HR-MANAGER), `EDP-BANK` dan `EDP-MEDICAL` (**tanpa atasan** — kondisi kesehatan bukan bahan penilaian kinerja, dan nomor rekening dipakai untuk membayar orang). `field_identity` sengaja **tidak** diseed: NIK dipakai sehari-hari untuk BPJS dan pajak.

---

## Import

Importer paling lengkap di sistem ini: Employee + organization + employment + payroll (PTKP) + bank + pendidikan, upsert by `employee_number`.

Detail dan jebakannya (PTKP vs Marital Status, format tanggal US, `hire_date` yang mengisi dua target) di [Framework Overview](../../02-Framework/Overview.md#import-generik).

---

## Checklist

- [ ] Kolom employment baru: **empat sentuhan**
- [ ] Kolom yang jadi tabel punya `<relasi>_name` di serializer
- [ ] Kolom terkunci ditambahkan ke `PROTECTED_FIELDS` kalau memang butuh Employee Action
- [ ] Kolom sensitif dipertimbangkan untuk `EmployeeDataPolicy` — **dan ketiga jalurnya**
- [ ] Regenerate + buka di browser
