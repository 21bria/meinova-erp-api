from apps.administration.models.references.hr import (
    BloodType,
    CertificateType,
    Degree,
    Education,
    StudyField,
    EmploymentStatus,
    ContractType,
    ProbationType,
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
    LicenseType,
    MaritalStatus,
    Nationality,
    Religion,
    Skill,
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

    EmploymentType: [
        {"code": "PERM", "name": "Permanent"},
        {"code": "CONT", "name": "Contract"},
        {"code": "DAILY", "name": "Daily Worker"},
        {"code": "INTERN", "name": "Intern"},
        {"code": "OUTSOURCE", "name": "Outsourcing"},
        {"code": "CONSULTANT", "name": "Consultant"},
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
}


def seed_hr_reference():
    for model, rows in HR_SEEDS.items():
        seed_reference(model, rows)