# Head Office vs Site

**Status: IMPLEMENTED**

Perbedaan paling besar dalam operasi HR perusahaan tambang adalah antara orang kantor dan orang lapangan. Sistem ini menanganinya **tanpa satu baris pun aturan industri yang ditanam di kode**.

---

## Tidak ada "modul site"

!!! success "Head Office dan Site adalah dua baris Work Location"
    Tidak ada model Site tersendiri. Tidak ada penanda `is_head_office`. Tidak ada percabangan "kalau tambang maka...".

    Yang membedakan keduanya adalah **apa yang ditempelkan ke baris lokasi itu**.

| Yang ditempelkan | Efeknya |
|---|---|
| **Work Calendar** | hari kerja mingguan — kantor Senin–Jumat, site tujuh hari |
| **Attendance Policy** | toleransi keterlambatan, ambang lembur |
| **Roster Policy** | pola siklus kerja/field break, hari perjalanan, kredit rotasi |
| **Workflow Definition** | siapa yang menyetujui dokumen di lokasi itu |
| **Holiday** | hari libur yang hanya berlaku di lokasi itu |

Menambah site baru berarti menambah satu baris lokasi dan mengonfigurasi lima hal di atas. Tidak ada rilis perangkat lunak yang diperlukan.

---

## Dua pola kerja

=== "Head Office"

    ```mermaid
    flowchart LR
        E["Pegawai kantor"] --> WC["Work Calendar<br/>Senin–Jumat"]
        WC --> H["dikurangi hari libur"]
        H --> SH["Shift kantor<br/>10:00–18:00"]
        SH --> P["Planned Work Day"]
        style P fill:#166534,color:#fff
    ```

    - hari kerjanya dari kalender mingguan;
    - akhir pekan tidak menghasilkan jadwal sama sekali;
    - hari libur nasional dikecualikan;
    - jam kerjanya satu shift tetap.

=== "Site"

    ```mermaid
    flowchart LR
        E["Pegawai site"] --> RP["Roster Policy<br/>42 kerja / 14 off"]
        RP --> SU["Roster Setup<br/>dokumen penjadwalan"]
        SU --> RO["Rencana Roster"]
        RO --> SEG["Segmen:<br/>Work · Field Break<br/>Travel Out · Travel In"]
        SEG --> SH["Rotasi shift<br/>pagi → malam → sore"]
        SH --> P["Planned Work Day"]
        style P fill:#166534,color:#fff
    ```

    - hari kerjanya dari **blok rotasi yang benar-benar diterbitkan**, bukan dari rumus siklus;
    - kalender site berjalan tujuh hari seminggu — yang menentukan libur adalah rosternya, bukan akhir pekan;
    - hari perjalanan punya segmennya sendiri;
    - shift berganti antar blok mengikuti rotasi policy, termasuk shift malam yang melewati tengah malam.

---

## Pegawai kantor yang berkantor di site

Ini kasus nyata yang sering salah ditangani sistem lain: seorang staf administrasi yang duduk di site tetapi jam kerjanya jam kantor.

**Di sistem ini ia tetap pegawai kalender, bukan pegawai roster.** Lokasinya site, tetapi tidak ada Roster Policy yang menempel padanya, jadi jadwalnya tetap dari Work Calendar.

!!! note "Kenapa ini perlu dinyatakan sadar"
    Layar Roster Setup menawarkan **semua** pegawai di lokasi itu yang belum punya rencana — termasuk pegawai kantor. Itu disengaja: di tenant baru, pegawai yang belum punya Roster Policy justru merekalah yang perlu disetup.

    Tapi begitu dokumennya di-commit, pegawai itu **berubah jadi pegawai roster** — Roster Policy ditulis ke data kepegawaiannya, dan sumber jadwalnya berpindah dari kalender ke blok rotasi.

    Jadi memilih siapa yang masuk dokumen Roster Setup adalah keputusan HR yang punya akibat permanen, bukan sekadar memilih isi daftar.

---

## Perbedaannya dalam angka

Contoh dari dataset peragaan yang berjalan (**CONFIGURED FOR DEMO**):

| | Jakarta Head Office | Sagea Mine |
|---|---|---|
| Kalender | Senin–Jumat | tujuh hari |
| Toleransi keterlambatan | 15 menit | 0 menit |
| Ambang lembur | 30 menit | 30 menit |
| Pola kerja | shift kantor tetap | 42 hari kerja / 14 hari field break, rotasi tiga shift |
| Hari libur berlaku | libur nasional | libur nasional **+ hari libur operasional site** |

Toleransi 15 menit di kantor pusat dan 0 di site bukan kesewenangan: orang kantor menempuh kemacetan Jakarta, orang site tinggal di mess seratus meter dari pos.
