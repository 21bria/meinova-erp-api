# Meinova ERP — People, Access & Organization Framework

## Framework Overview

                    ORGANIZATION & PEOPLE
                           │
                           ▼
                    ┌─────────────┐
                    │  EMPLOYEE   │
                    │ Siapa dia?  │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
       EMPLOYEE GROUP   REPORTING     USER ACCOUNT
       Kelompoknya?       LINE        Akun sistem
              │         Atasannya?          │
              ▼                            ▼
        APPLICABILITY                     ROLE
       Proses apa yang              Bisa melakukan apa?
        berlaku?                           │
              │                            ▼
              │                   ORGANIZATION SCOPE
              │                    Bisa lihat mana?
              │                            │
              └────────────┬───────────────┘
                           ▼
                     BUSINESS PROCESS
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
      ATTENDANCE        WORKFLOW         ROSTER
        LEAVE           APPROVAL          SHIFT
      OVERTIME         TRANSACTION      FIELD BREAK
                           │
                           ▼
                  DASHBOARD & REPORTS
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
       PERIOD SUMMARY           EMPLOYEE REPORTING
       Operational Result       Organization Audit


## Core Principles

**Employee Group** → proses apa yang berlaku  
**Reporting Line** → siapa melapor kepada siapa  
**Role** → apa yang boleh dilakukan  
**Organization Scope** → data mana yang boleh dilihat  


## Management Example — BOD

BOD tetap merupakan **Employee** dan tetap berada dalam struktur organisasi.

Attendance, Roster, Shift, atau proses operasional lainnya dapat ditetapkan sebagai **Not Applicable**, tanpa menghilangkan BOD dari Employee Master maupun struktur organisasi.

Ketika mempunyai **User Account**, BOD memperoleh kemampuan melalui **Role**, sedangkan cakupan company/location yang dapat dilihat ditentukan melalui **Organization Scope**.

**Reporting Line** tetap membentuk hubungan organisasi sampai level BOD dan tidak bergantung pada Feature Applicability.


## Operational Result vs Organization Audit

### Period Summary

Menunjukkan hasil proses operasional employee.

**Employee → Applicability → Business Process → Period Summary**

Employee yang prosesnya **Not Applicable** tidak dipaksakan masuk sebagai baris operasional kosong.


### Employee Reporting

Menunjukkan struktur organisasi dan hubungan reporting employee.

**Employee Master → Reporting Line → User Account → Employee Reporting**

Employee tetap terlihat sebagai bagian organisasi walaupun proses tertentu **Not Applicable**.


## Business Rule

    Perubahan proses employee
            ↓
    Employee Group / Applicability

    Perubahan atasan
            ↓
    Reporting Line

    Perubahan kewenangan
            ↓
    Role

    Perubahan cakupan data
            ↓
    Organization Scope


## Management Summary

    ONE EMPLOYEE MASTER
            │
            ▼
    CONFIGURABLE BUSINESS RULES
            │
            ▼
    CONTROLLED ACCESS
            │
            ▼
    CLEAR REPORTING LINE
            │
            ▼
    BUSINESS PROCESS
            │
            ▼
    MANAGEMENT REPORTING


> **One Employee Master → Configurable Business Rules → Controlled Access → Clear Reporting Line → Business Process → Management Reporting**