# HR Attendance Architecture

## Overview

Attendance terdiri dari beberapa master yang saling berhubungan.

```
Employee
    │
    ├── Work Schedule
    │       │
    │       ├── Work Schedule Day
    │       └── Shift
    │
    └── Working Calendar
            │
            └── Holidays
```

---

# Work Schedule

Work Schedule mendefinisikan **pola kerja** seorang karyawan.

Contoh:

| Code  | Name           | Pattern      |
|-------|----------------|--------------|
| REG5  | Regular 5 Days | Mon–Fri      |
| REG6  | Regular 6 Days | Mon–Sat      |
| ROS14 | Mining 14/14   | 14 On 14 Off |
| ROS21 | Mining 21/7    | 21 On 7 Off  |
| FLEX  | Flexible       | Flexible     |. 

Work Schedule dapat terdiri dari beberapa Shift.

---

# Shift

Shift adalah jam kerja.

Contoh:

| Name      | Start | End   |
|-----------|-------|-------|
| Morning   | 08:00 | 17:00 |
| Afternoon | 15:00 | 23:00 |
| Night     | 23:00 | 07:00 |

Shift dapat digunakan oleh banyak Work Schedule.

---

# Work Schedule Day

Menyimpan detail setiap hari.

Contoh:

Regular 5 Days

Monday
    Shift Morning

Tuesday
    Shift Morning

Wednesday
    Shift Morning

Thursday
    Shift Morning

Friday
    Shift Morning

Saturday
    Off

Sunday
    Off

---

# Working Calendar

Working Calendar mendefinisikan hari kerja perusahaan.

Contoh:

Indonesia 2027

01 Jan
Holiday

29 Mar
Nyepi

17 Aug
Independence Day

25 Dec
Christmas

---

# Holiday

Holiday merupakan detail dari Working Calendar.

Contoh:

Working Calendar : Indonesia 2027

Holiday
---------
01 Jan
29 Mar
17 Aug
25 Dec

---

# Difference

## Work Schedule

Menjawab pertanyaan:

> Karyawan bekerja bagaimana?

Contoh:

- Regular 5 Days
- Regular 6 Days
- Mining 14/14
- Flexible

---

## Working Calendar

Menjawab pertanyaan:

> Hari apa saja perusahaan libur?

Contoh:

- New Year
- Christmas
- Company Shutdown
- National Holiday

---

# Example

Employee

Name

John Doe

Work Schedule

Mining 14/14

Working Calendar

Indonesia 2027

Shift

Morning

Result

John bekerja:

- 14 hari kerja
- 14 hari libur
- mengikuti kalender Indonesia 2027
- menggunakan Shift Morning

---

# ERP Structure

Attendance Master

- Shift Groups
- Shifts
- Work Schedules
- Working Calendars
- Holidays

Attendance Transaction

- Shift Assignment
- Attendance
- Overtime
- Leave
- Attendance Adjustment