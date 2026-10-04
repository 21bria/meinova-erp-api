from apps.administration.models.references.hr import (
    BloodType,
    CertificateType,
    Degree,
    Education,
    StudyField,
    EmploymentStatus,
    ContractType,
    ProbationType,
    TerminationReason,
    EmploymentType,
    EmployeeGroup,
    FamilyRelationship,
    Gender,
    JobCategory,
    JobFamily,
    JobLevel,
    JobGrade,
    Language,
    LeaveReason,
    LeaveType,
    RotationPurpose,
    LicenseType,
    MaritalStatus,
    Nationality,
    OvertimeType,
    Religion,
    Skill,
    DocumentType,
    TrainingCategory,
    TrainingProvider,
    CandidateStatus,
    InterviewType,
    RecruitmentSource,
    RejectionReason,
    TransportMode,
    AccommodationType,
)

# Visitor Management — master baru, berkas modelnya sendiri.
from apps.administration.models.references.visitor import (
    VisitPurpose,
    VisitType,
)

from .base import seed_reference


HR_SEEDS = {
    Gender: [
        {"code": "M", "name": "Male"},
        {"code": "F", "name": "Female"},
    ],

    Religion: [
        {"code": "ISLAM", "name": "Islam"},
        {"code": "PROTESTANT", "name": "Protestant"},
        {"code": "CATHOLIC", "name": "Catholic"},
        {"code": "HINDU", "name": "Hindu"},
        {"code": "BUDDHA", "name": "Buddha"},
        {"code": "CONFUCIAN", "name": "Confucian"},
    ],

    Nationality: [
        {"code": "ID", "name": "Indonesian"},
        {"code": "SG", "name": "Singaporean"},
        {"code": "MY", "name": "Malaysian"},
    ],

    BloodType: [
        {"code": "A", "name": "A"},
        {"code": "B", "name": "B"},
        {"code": "AB", "name": "AB"},
        {"code": "O", "name": "O"},
    ],

    MaritalStatus: [
        {"code": "S", "name": "Single"},
        {"code": "M", "name": "Married"},
        {"code": "D", "name": "Divorced"},
        {"code": "W", "name": "Widowed"},
    ],

    Education: [
        {"code": "SMA", "name": "High School"},
        {"code": "D3", "name": "Diploma"},
        {"code": "S1", "name": "Bachelor"},
        {"code": "S2", "name": "Master"},
        {"code": "S3", "name": "Doctorate"},
    ],

    Degree: [
        {"code": "AMD", "name": "Associate Degree"},
        {"code": "SKOM", "name": "Bachelor of Computer Science"},
        {"code": "ST", "name": "Bachelor of Engineering"},
        {"code": "SE", "name": "Bachelor of Economics"},
        {"code": "MT", "name": "Master of Engineering"},
    ],

    StudyField: [
        {"code": "MINING", "name": "Mining Engineering"},
        {"code": "GEOLOGY", "name": "Geology"},
        {"code": "CIVIL", "name": "Civil Engineering"},
        {"code": "MECHANICAL", "name": "Mechanical Engineering"},
        {"code": "ELECTRICAL", "name": "Electrical Engineering"},
        {"code": "ACCOUNTING", "name": "Accounting"},
        {"code": "MANAGEMENT", "name": "Management"},
        {"code": "LAW", "name": "Law"},
        {"code": "IT", "name": "Information Technology"},
    ],

    # `requires_contract` menentukan jenis mana yang membawa masa
    # kontrak. Form employment memakainya untuk menyembunyikan kolom
    # Contract Type/Start/End pada pegawai tetap, dan
    # `EmploymentAssignment.clean()` memakainya untuk menolak Contract
    # End yang masih menempel di pegawai Permanent.
    EmploymentType: [
        {"code": "PERM", "name": "Permanent", "requires_contract": False},
        {"code": "CONT", "name": "Contract", "requires_contract": True},
        {"code": "DAILY", "name": "Daily Worker", "requires_contract": True},
        {"code": "INTERN", "name": "Intern", "requires_contract": True},
        {"code": "OUTSOURCE", "name": "Outsourcing", "requires_contract": True},
        {"code": "CONSULTANT", "name": "Consultant", "requires_contract": True},
    ],

    EmploymentStatus: [
        {"code": "ACTIVE", "name": "Active"},
        {"code": "PROBATION", "name": "Probation"},
        {"code": "LEAVE", "name": "On Leave"},
        {"code": "SUSPENDED", "name": "Suspended"},
        {"code": "RESIGN", "name": "Resigned"},
        {"code": "RETIRED", "name": "Retired"},
        {"code": "TERM", "name": "Terminated"},
    ],

    ContractType: [
        {"code": "PKWT", "name": "PKWT"},
        {"code": "PROJECT", "name": "Project Contract"},
        {"code": "SEASONAL", "name": "Seasonal Contract"},
        {"code": "VENDOR", "name": "Vendor Contract"},
    ],

    ProbationType: [
        {"code": "NONE", "name": "No Probation"},
        {"code": "STANDARD", "name": "Standard Probation"},
        {"code": "EXTENDED", "name": "Extended Probation"},
        {"code": "FASTTRACK", "name": "Fast Track"},
    ],

    # Tanpa baris-baris ini **tidak ada tenant yang bisa mencatat satu
    # pun kepergian**, dan kegagalannya menunggu sampai orang pertama
    # benar-benar resign: `EmploymentAssignment.clean()` mewajibkan
    # Termination Reason begitu Termination Date diisi, dan
    # `ACTION_FIELD_RULES` mewajibkannya untuk dokumen Termination.
    # Master-nya sendiri tidak pernah ikut di-seed, jadi satu-satunya
    # nilai yang tersedia adalah tidak ada — dan dokumen kepergiannya
    # berhenti di status approved dengan `apply_error` terisi.
    TerminationReason: [
        {"code": "RESIGN", "name": "Resignation"},
        {"code": "CONTRACT_END", "name": "Contract Ended"},
        {"code": "RETIRE", "name": "Retirement"},
        {"code": "MUTUAL", "name": "Mutual Agreement"},
        {"code": "PERFORMANCE", "name": "Performance"},
        {"code": "MISCONDUCT", "name": "Misconduct"},
        {"code": "REDUNDANCY", "name": "Redundancy"},
        {"code": "HEALTH", "name": "Health Reason"},
        {"code": "DECEASED", "name": "Deceased"},
        {"code": "OTHER", "name": "Other"},
    ],

    EmployeeGroup: [
        {"code": "LOCAL","name": "Local Employee"},
        {"code": "EXPAT","name": "Expatriate"},
        {"code": "MANAGEMENT","name": "Management"},
        {"code": "NON_MGMT","name": "Non Management"},
        {"code": "FIELD","name": "Field Employee"},
        {"code": "OFFICE","name": "Office Employee"},
        {"code": "PROJECT","name": "Project Employee"},
        {"code": "CONTRACTOR","name": "Contractor"},
        {"code": "TRAINEE","name": "Trainee"},
        {"code": "APPRENTICE","name": "Apprentice"},
        {"code": "BOARD","name": "Board of Directors"},
        {"code": "EXECUTIVE","name": "Executive"},
    ],

    JobCategory: [
        {"code": "OPS", "name": "Operations"},
        {"code": "TECH", "name": "Technical"},
        {"code": "ADMIN", "name": "Administration"},
        {"code": "SUPPORT", "name": "Support"},
        {"code": "MGMT", "name": "Management"},
    ],

    JobFamily: [
        {"code": "MINING", "name": "Mining"},
        {"code": "PROCESS", "name": "Processing Plant"},
        {"code": "ENGINEERING", "name": "Engineering"},
        {"code": "MAINTENANCE", "name": "Maintenance"},
        {"code": "HSE", "name": "Health Safety Environment"},
        {"code": "HR", "name": "Human Resources"},
        {"code": "FINANCE", "name": "Finance"},
        {"code": "PROCUREMENT", "name": "Procurement"},
        {"code": "LOGISTIC", "name": "Logistics"},
        {"code": "IT", "name": "Information Technology"},
        {"code": "LEGAL", "name": "Legal"},
    ],

    JobLevel: [
        {"code": "STAFF", "name": "Staff"},
        {"code": "SUP", "name": "Supervisor"},
        {"code": "SPV", "name": "Superintendent"},
        {"code": "MGR", "name": "Manager"},
        {"code": "GM", "name": "General Manager"},
        {"code": "DIR", "name": "Director"},
    ],

    JobGrade:[
        {"code": "G01","name": "Grade 1","job_level": "STAFF","description": "Entry Level"},
        {"code": "G02","name": "Grade 2","job_level": "STAFF","description": "Junior Staff"},
        {"code": "G03","name": "Grade 3","job_level": "STAFF","description": "Staff"},
        {"code": "G04","name": "Grade 4","job_level": "STAFF","description": "Senior Staff"},
        {"code": "G05","name": "Grade 5","job_level": "SUP","description": "Supervisor"},
        {"code": "G06","name": "Grade 6","job_level": "SUP","description": "Senior Supervisor"},
        {"code": "G07","name": "Grade 7","job_level": "SUP","description": "Superintendent"},
        {"code": "G08","name": "Grade 8","job_level": "MGR","description": "Manager"},
        {"code": "G09","name": "Grade 9","job_level": "MGR","description": "Senior Manager" },
        {"code": "G10","name": "Grade 10","job_level": "GM","description": "General Manager"},
        {"code": "G11","name": "Grade 11","job_level": "DIR","description": "Director"},
        {"code": "G12","name": "Grade 12","job_level": "DIR","description": "President Director"},
    ],



    Skill: [
        {"code": "EXCEL", "name": "Microsoft Excel"},
        {"code": "LEAD", "name": "Leadership"},
        {"code": "SAFETY", "name": "Occupational Safety"},
    ],

    CertificateType: [
        {"code": "BNSP", "name": "BNSP Certificate"},
        {"code": "K3", "name": "K3 Certificate"},
        {"code": "FIRSTAID", "name": "First Aid Certificate"},
    ],

    LicenseType: [
        {"code": "SIM-A", "name": "Driving License A"},
        {"code": "SIM-B2", "name": "Driving License B2"},
        {"code": "SIO", "name": "Operator License"},
    ],

    Language: [
        {"code": "ID", "name": "Indonesian"},
        {"code": "EN", "name": "English"},
        {"code": "ZH", "name": "Mandarin"},
    ],

    FamilyRelationship: [
        {"code": "SPOUSE", "name": "Spouse"},
        {"code": "CHILD", "name": "Child"},
        {"code": "PARENT", "name": "Parent"},
        {"code": "SIBLING", "name": "Sibling"},
    ],

    LeaveReason: [
        {"code": "SICK", "name": "Sick Leave"},
        {"code": "ANNUAL", "name": "Annual Leave"},
        {"code": "MATERNITY", "name": "Maternity Leave"},
        {"code": "PERSONAL", "name": "Personal Leave"},
    ],

    # Jenis cuti mengikuti UU Ketenagakerjaan Indonesia. Ini yang
    # dirujuk EmployeeLeave dan LeaveBalance — tanpa seed ini modul
    # Leave tidak bisa dipakai sama sekali.
    # Master jenis cuti.
    # Detail hak, jumlah hari, dokumen, eligibility, dan aturan penggunaan
    # TIDAK di-hardcode di LeaveType — semuanya diatur melalui LeavePolicy.
    #
    # ANNUAL adalah leave berbasis saldo.
    # Jenis cuti lainnya pada dasarnya divalidasi berdasarkan rule/policy
    # ketika EmployeeLeave diajukan.

    LeaveType: [
        {"code": "ANNUAL", "name": "Cuti Tahunan", "sort_order": 10},

        {"code": "SICK", "name": "Cuti Sakit", "sort_order": 20},

        {"code": "MATERNITY", "name": "Cuti Melahirkan", "sort_order": 30},
        {"code": "MISCARRIAGE", "name": "Cuti Keguguran", "sort_order": 40},
        {"code": "PATERNITY", "name": "Cuti Suami/Istri Melahirkan", "sort_order": 50},

        {"code": "MARRIAGE", "name": "Cuti Menikah", "sort_order": 60},
        {"code": "CHILD_MARRIAGE", "name": "Cuti Menikahkan Anak", "sort_order": 70},
        {"code": "CHILD_CIRCUMCISION", "name": "Cuti Khitan Anak", "sort_order": 80},
        {"code": "CHILD_BAPTISM", "name": "Cuti Baptis Anak", "sort_order": 90},

        {"code": "BEREAVEMENT", "name": "Cuti Kedukaan", "sort_order": 100},

        {"code": "HAJJ", "name": "Cuti Ibadah Haji", "sort_order": 110},
        {"code": "RELIGIOUS", "name": "Cuti Keagamaan / Ibadah", "sort_order": 120},

        {"code": "SPECIAL", "name": "Cuti Khusus", "sort_order": 130},

        {"code": "UNPAID", "name": "Cuti Tanpa Upah", "sort_order": 140},

        {"code": "BIG", "name": "Cuti Besar", "sort_order": 150},
    ],

    OvertimeType: [
        {"code": "WEEKDAY", "name": "Lembur Hari Kerja", "sort_order": 10},
        {"code": "WEEKEND", "name": "Lembur Hari Libur", "sort_order": 20},
        {"code": "HOLIDAY", "name": "Lembur Hari Besar", "sort_order": 30},
        {"code": "CALL_OUT", "name": "Lembur Panggilan", "sort_order": 40},
    ],

    RecruitmentSource: [
        {"code": "JOBSTREET", "name": "JobStreet", "sort_order": 10},
        {"code": "LINKEDIN", "name": "LinkedIn", "sort_order": 20},
        {"code": "REFERRAL", "name": "Referensi Karyawan", "sort_order": 30},
        {"code": "WALK_IN", "name": "Walk In", "sort_order": 40},
        {"code": "CAMPUS", "name": "Campus Hiring", "sort_order": 50},
        {"code": "AGENCY", "name": "Agen Rekrutmen", "sort_order": 60},
        {"code": "WEBSITE", "name": "Website Perusahaan", "sort_order": 70},
        {"code": "INTERNAL", "name": "Mutasi Internal", "sort_order": 80},
    ],

    CandidateStatus: [
        {"code": "APPLIED", "name": "Melamar", "sort_order": 10},
        {"code": "SCREENING", "name": "Seleksi Berkas", "sort_order": 20},
        {"code": "INTERVIEW", "name": "Wawancara", "sort_order": 30},
        {"code": "TEST", "name": "Tes", "sort_order": 40},
        {"code": "OFFERING", "name": "Penawaran", "sort_order": 50},
        {"code": "HIRED", "name": "Diterima", "sort_order": 60},
        {"code": "REJECTED", "name": "Ditolak", "sort_order": 70},
        {"code": "WITHDRAWN", "name": "Mengundurkan Diri", "sort_order": 80},
    ],

    InterviewType: [
        {"code": "HR", "name": "Wawancara HR", "sort_order": 10},
        {"code": "USER", "name": "Wawancara User", "sort_order": 20},
        {"code": "TECHNICAL", "name": "Wawancara Teknis", "sort_order": 30},
        {"code": "MANAGEMENT", "name": "Wawancara Manajemen", "sort_order": 40},
        {"code": "PSYCHOTEST", "name": "Psikotes", "sort_order": 50},
        {"code": "MEDICAL", "name": "Tes Kesehatan", "sort_order": 60},
    ],

    RejectionReason: [
        {"code": "QUALIFICATION", "name": "Kualifikasi Tidak Sesuai", "sort_order": 10},
        {"code": "EXPERIENCE", "name": "Pengalaman Kurang", "sort_order": 20},
        {"code": "SALARY", "name": "Ekspektasi Gaji Tidak Cocok", "sort_order": 30},
        {"code": "LOCATION", "name": "Lokasi Tidak Sesuai", "sort_order": 40},
        {"code": "NO_SHOW", "name": "Tidak Hadir Wawancara", "sort_order": 50},
        {"code": "POSITION_CLOSED", "name": "Lowongan Ditutup", "sort_order": 60},
        {"code": "OTHER", "name": "Lainnya", "sort_order": 70},
    ],

    DocumentType: [
        {
            "code": "KTP",
            "name": "National ID Card",
            "category": "IDENTITY",
            "is_required": True,
            "is_expirable": False,
            "requires_number": True,
            "requires_issue_date": False,
            "requires_expiry_date": False,
            "requires_issuing_authority": False,
            "allow_multiple": False,
            "sort_order": 10,
        },
        {
            "code": "FAMILY_CARD",
            "name": "Family Card",
            "category": "FAMILY",
            "is_required": True,
            "is_expirable": False,
            "requires_number": True,
            "requires_issue_date": False,
            "requires_expiry_date": False,
            "requires_issuing_authority": False,
            "allow_multiple": False,
            "sort_order": 20,
        },
        {
            "code": "NPWP",
            "name": "Tax Identification Number",
            "category": "TAX",
            "is_required": False,
            "is_expirable": False,
            "requires_number": True,
            "requires_issue_date": False,
            "requires_expiry_date": False,
            "requires_issuing_authority": False,
            "allow_multiple": False,
            "sort_order": 30,
        },
        {
            "code": "PASSPORT",
            "name": "Passport",
            "category": "IMMIGRATION",
            "is_required": False,
            "is_expirable": True,
            "requires_number": True,
            "requires_issue_date": True,
            "requires_expiry_date": True,
            "requires_issuing_authority": True,
            "allow_multiple": False,
            "sort_order": 40,
        },
        {
            "code": "DRIVING_LICENSE",
            "name": "Driving License",
            "category": "LICENSE",
            "is_required": False,
            "is_expirable": True,
            "requires_number": True,
            "requires_issue_date": True,
            "requires_expiry_date": True,
            "requires_issuing_authority": True,
            "allow_multiple": False,
            "sort_order": 50,
        },
        {
            "code": "DIPLOMA",
            "name": "Diploma",
            "category": "EDUCATION",
            "is_required": False,
            "is_expirable": False,
            "requires_number": True,
            "requires_issue_date": True,
            "requires_expiry_date": False,
            "requires_issuing_authority": True,
            "allow_multiple": False,
            "sort_order": 60,
        },
        {
            "code": "ACADEMIC_TRANSCRIPT",
            "name": "Academic Transcript",
            "category": "EDUCATION",
            "is_required": False,
            "is_expirable": False,
            "requires_number": False,
            "requires_issue_date": True,
            "requires_expiry_date": False,
            "requires_issuing_authority": True,
            "allow_multiple": False,
            "sort_order": 70,
        },
        {
            "code": "PROFESSIONAL_CERTIFICATE",
            "name": "Professional Certificate",
            "category": "EDUCATION",
            "is_required": False,
            "is_expirable": True,
            "requires_number": True,
            "requires_issue_date": True,
            "requires_expiry_date": False,
            "requires_issuing_authority": True,
            "allow_multiple": True,
            "sort_order": 80,
        },
        {
            "code": "EMPLOYMENT_CONTRACT",
            "name": "Employment Contract",
            "category": "EMPLOYMENT",
            "is_required": True,
            "is_expirable": True,
            "requires_number": True,
            "requires_issue_date": True,
            "requires_expiry_date": False,
            "requires_issuing_authority": True,
            "allow_multiple": False,
            "sort_order": 90,
        },
        {
            "code": "REFERENCE_LETTER",
            "name": "Employment Reference Letter",
            "category": "EMPLOYMENT",
            "is_required": False,
            "is_expirable": False,
            "requires_number": False,
            "requires_issue_date": True,
            "requires_expiry_date": False,
            "requires_issuing_authority": True,
            "allow_multiple": True,
            "sort_order": 100,
        },
        {
            "code": "BPJS_HEALTH",
            "name": "BPJS Health Card",
            "category": "HEALTH",
            "is_required": False,
            "is_expirable": False,
            "requires_number": True,
            "requires_issue_date": False,
            "requires_expiry_date": False,
            "requires_issuing_authority": False,
            "allow_multiple": False,
            "sort_order": 110,
        },
        {
            "code": "BPJS_EMPLOYMENT",
            "name": "BPJS Employment Card",
            "category": "EMPLOYMENT",
            "is_required": False,
            "is_expirable": False,
            "requires_number": True,
            "requires_issue_date": False,
            "requires_expiry_date": False,
            "requires_issuing_authority": False,
            "allow_multiple": False,
            "sort_order": 120,
        },
        {
            "code": "BANK_BOOK",
            "name": "Bank Account Book",
            "category": "FINANCE",
            "is_required": False,
            "is_expirable": False,
            "requires_number": True,
            "requires_issue_date": False,
            "requires_expiry_date": False,
            "requires_issuing_authority": True,
            "allow_multiple": False,
            "sort_order": 130,
        },
        {
            "code": "CV",
            "name": "Curriculum Vitae",
            "category": "EMPLOYMENT",
            "is_required": False,
            "is_expirable": False,
            "requires_number": False,
            "requires_issue_date": False,
            "requires_expiry_date": False,
            "requires_issuing_authority": False,
            "allow_multiple": False,
            "sort_order": 140,
        },
        {
            "code": "PHOTO",
            "name": "Employee Photo",
            "category": "IDENTITY",
            "is_required": False,
            "is_expirable": False,
            "requires_number": False,
            "requires_issue_date": False,
            "requires_expiry_date": False,
            "requires_issuing_authority": False,
            "allow_multiple": False,
            "sort_order": 150,
        },
        {
            "code": "OTHER",
            "name": "Other Document",
            "category": "OTHER",
            "is_required": False,
            "is_expirable": False,
            "requires_number": False,
            "requires_issue_date": False,
            "requires_expiry_date": False,
            "requires_issuing_authority": False,
            "allow_multiple": True,
            "sort_order": 999,
        },
    ],
    TrainingCategory: [
        {"code": "SAFETY_IND", "name": "Safety Induction"},
        {"code": "HSE_AWARE", "name": "HSE Awareness"},
        {"code": "FIRST_AID", "name": "First Aid"},
        {"code": "FIRE_FIGHT", "name": "Fire Fighting"},
        {"code": "EMERGENCY", "name": "Emergency Response"},
        {"code": "WORK_HEIGHT", "name": "Working at Height"},
        {"code": "CONFINED", "name": "Confined Space"},
        {"code": "HEAVY_EQUIP", "name": "Heavy Equipment Operation"},
        {"code": "DEF_DRIVE", "name": "Defensive Driving"},
        {"code": "MINE_SAFE", "name": "Mine Safety"},
    ],

    TrainingProvider: [
        {"code": "UTTC", "name": "PT United Tractors Training Center"},
        {"code": "TRAKINDO", "name": "PT Trakindo Training Center"},
        {"code": "SUCOFINDO", "name": "PT Sucofindo"},
        {"code": "SURVEYOR", "name": "PT Surveyor Indonesia"},
        {"code": "BNSP", "name": "BNSP"},
        {"code": "KEMNAKER", "name": "Kemnaker RI"},
        {"code": "PJK3", "name": "PJK3 Indonesia"},
        {"code": "MSI", "name": "Mine Safety Institute"},
        {"code": "INTERNAL", "name": "Internal Company Trainer"},
        {"code": "MEINOVA", "name": "Meinova Training Center"},
    ],

    # Mobilisasi pegawai site. Daftar ini sengaja condong ke kepulauan
    # timur Indonesia — rute tambang lazimnya pesawat ke kota terdekat
    # lalu kapal/speedboat ke lokasi.
    TransportMode: [
        {"code": "FLIGHT", "name": "Flight", "sort_order": 10},
        {"code": "BOAT", "name": "Boat", "sort_order": 20},
        {"code": "SPEEDBOAT", "name": "Speedboat", "sort_order": 30},
        {"code": "FERRY", "name": "Ferry", "sort_order": 40},
        {"code": "CAR", "name": "Car", "sort_order": 50},
        {"code": "BUS", "name": "Bus", "sort_order": 60},
        {"code": "TRAIN", "name": "Train", "sort_order": 70},
        {"code": "HELI", "name": "Helicopter", "sort_order": 80},
        {"code": "OTHER", "name": "Other", "sort_order": 999},
    ],

    AccommodationType: [
        {"code": "HOTEL", "name": "Hotel", "sort_order": 10},
        {"code": "GUESTHOUSE", "name": "Guest House", "sort_order": 20},
        {"code": "MESS", "name": "Company Mess", "sort_order": 30},
        {"code": "CAMP", "name": "Site Camp", "sort_order": 40},
        {"code": "APARTMENT", "name": "Apartment", "sort_order": 50},
        {"code": "OTHER", "name": "Other", "sort_order": 999},
    ],

    # -------------------------------------------------------------------------
    # Visitor Management
    # -------------------------------------------------------------------------
    #
    # Label Inggris, mengikuti konvensi seluruh master di berkas ini —
    # help text dan komentar yang berbahasa Indonesia, bukan isinya.
    VisitPurpose: [
        {"code": "MEETING", "name": "Business Meeting", "sort_order": 10},
        {"code": "SITE-VISIT", "name": "Site Visit", "sort_order": 20},
        {"code": "INSPECTION", "name": "Inspection", "sort_order": 30},
        {"code": "AUDIT", "name": "Audit", "sort_order": 40},
        {"code": "TRAINING", "name": "Training", "sort_order": 50},
        {"code": "INTERVIEW", "name": "Interview", "sort_order": 60},
        {"code": "VENDOR", "name": "Vendor Visit", "sort_order": 70},
        {"code": "CUSTOMER", "name": "Customer Visit", "sort_order": 80},
        {"code": "OFFICIAL", "name": "Official Visit", "sort_order": 90},
        {"code": "MAINTENANCE", "name": "Maintenance / Service", "sort_order": 100},
        {"code": "DELIVERY", "name": "Delivery", "sort_order": 110},
        {"code": "OTHER", "name": "Other", "sort_order": 999},
    ],

    VisitType: [
        {"code": "OFFICIAL", "name": "Official", "sort_order": 10},
        {"code": "VENDOR", "name": "Vendor / Supplier", "sort_order": 20},
        {"code": "CUSTOMER", "name": "Customer", "sort_order": 30},
        {"code": "CONTRACTOR", "name": "Contractor", "sort_order": 40},
        {"code": "GOVERNMENT", "name": "Government", "sort_order": 50},
        # BT-2A: pegawai berkunjung = Business Trip. Dinonaktifkan, bukan
        # dihapus — dokumen lama masih menunjuknya (PROTECT).
        {"code": "INTERNAL", "name": "Internal", "sort_order": 60, "is_active": False},
        {"code": "PERSONAL", "name": "Personal", "sort_order": 70},
        {"code": "OTHER", "name": "Other", "sort_order": 999},
    ],
}


# Alasan blok off pada roster site — "Travel Purpose" di form Travel
# Request. Diseed terpisah dari HR_SEEDS karena barisnya menunjuk
# LeaveType, dan seeder generik mencocokkan by `code` tanpa bisa
# menyelesaikan relasi.
#
# `deducts_leave` yang membedakan dua jenis barang di formulir aslinya:
# Field Break adalah blok off rosternya sendiri dan tidak memotong saldo
# apa pun, sedangkan Cuti Tahunan memotong.
ROTATION_PURPOSES = [
    ("FB", "Field Break", False, None, 10),
    ("ANNUAL", "Cuti Tahunan", True, "ANNUAL", 20),
    ("SICK", "Sakit", True, "SICK", 30),
    ("BIG", "Cuti Besar", True, "BIG", 40),
    ("UNPAID", "Cuti Tanpa Gaji", True, "UNPAID", 50),
    ("DUTY", "Dinas Luar", False, None, 60),
    ("TRAINING", "Training", False, None, 70),
    ("DEMOB", "Demobilisasi", False, None, 80),
]


def seed_rotation_purposes():
    leave_types = {
        item.code: item
        for item in LeaveType.objects.filter(is_deleted=False)
    }

    rows = []

    for code, name, deducts, leave_code, sort_order in ROTATION_PURPOSES:
        leave_type = (
            leave_types.get(leave_code)
            if leave_code
            else None
        )

        # Alasan pemotong saldo yang jenis cutinya belum ada di master
        # sengaja dilewati, bukan diseed tanpa relasi: barisnya akan
        # ditolak `RotationPurpose.clean()` dan lebih baik hilang daripada
        # ada tapi tidak bisa dipakai menghitung.
        if deducts and leave_type is None:
            continue

        rows.append(
            {
                "code": code,
                "name": name,
                "deducts_leave": deducts,
                "leave_type": leave_type,
                "sort_order": sort_order,
            },
        )

    seed_reference(RotationPurpose, rows)


def seed_hr_reference():
    for model, rows in HR_SEEDS.items():
        seed_reference(model, rows)

    # Setelah HR_SEEDS, karena barisnya menunjuk LeaveType yang baru saja
    # dibuat di atas.
    seed_rotation_purposes()