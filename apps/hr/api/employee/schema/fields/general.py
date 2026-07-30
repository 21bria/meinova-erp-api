from apps.framework.builders import field


GENERAL_FIELDS = {
    "user": field.lookup(
        tab="general",
        label="User Account",
        lookup_endpoint="/api/accounts/lookup/users/",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=10,
    ),

    "employee_number": field.text(
        tab="general",
        label="Employee Number",
        placeholder="e.g. EMP-0001",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=20,
    ),

    "nik": field.text(
        tab="general",
        label="NIK",
        placeholder="National identity number",
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=30,
    ),

    "passport_number": field.text(
        tab="general",
        label="Passport Number",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=40,
    ),

    "tax_number": field.text(
        tab="general",
        label="NPWP",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=50,
    ),

    "first_name": field.text(
        tab="general",
        label="First Name",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=60,
    ),

    "last_name": field.text(
        tab="general",
        label="Last Name",
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=80,
    ),


    "gender": field.lookup(
        tab="general",
        label="Gender",
        lookup_endpoint="/api/administration/references/hr/lookup/genders/",
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=100,
    ),

    "religion": field.lookup(
        tab="general",
        label="Religion",
        lookup_endpoint="/api/administration/references/hr/lookup/religions/",
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=110,
    ),

    "nationality": field.lookup(
        tab="general",
        label="Nationality",
        lookup_endpoint="/api/administration/references/hr/lookup/nationalities/",
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=120,
    ),

    "blood_type": field.lookup(
        tab="general",
        label="Blood Type",
        lookup_endpoint="/api/administration/references/hr/lookup/blood-types/",
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=130,
    ),

    "marital_status": field.lookup(
        tab="general",
        label="Marital Status",
        lookup_endpoint="/api/administration/references/hr/lookup/marital-statuses/",
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=140,
    ),

    "birth_place": field.text(
        tab="general",
        label="Birth Place",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=150,
    ),

    "birth_date": field.date(
        tab="general",
        label="Birth Date",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=160,
    ),

    "personal_email": field.email(
        tab="general",
        label="Personal Email",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=170,
    ),

    "work_email": field.email(
        tab="general",
        label="Work Email",
        table=True,
        filter=False,
        search=True,
        sortable=True,
        order=180,
    ),

    "phone": field.text(
        tab="general",
        label="Phone",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=190,
    ),

    "mobile": field.text(
        tab="general",
        label="Mobile",
        table=True,
        filter=False,
        search=True,
        sortable=False,
        order=200,
    ),

    "emergency_contact_name": field.text(
        tab="general",
        label="Emergency Contact Name",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=210,
    ),

    "emergency_contact_phone": field.text(
        tab="general",
        label="Emergency Contact Phone",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=220,
    ),

    "avatar": field.image(
        tab="general",
        label="Avatar",
        accept="image/*",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=230,
    ),

    "notes": field.textarea(
        tab="general",
        label="Notes",
        placeholder="Write employee notes...",
        layout="full",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=240,
    ),

    "is_active": field.boolean(
        tab="general",
        label="Active",
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=999,
    ),
}