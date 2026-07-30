from apps.framework.builders import tabs


EMPLOYEE_TABS = [
    tabs.form(
        key="general",
        label="General",
        order=10,
        show_on_create=True,
    ),

    tabs.form(
        key="organization",
        label="Organization",
        order=20,
        show_on_create=True,
    ),

    tabs.form(
        key="employment",
        label="Employment",
        order=30,
        show_on_create=True,
    ),

    tabs.form(
        key="payroll",
        label="Payroll",
        order=40,
        show_on_create=True,
    ),

    tabs.resource(
        key="bank",
        label="Bank Accounts",
        resource="employee-bank",
        requires_record=True,
        show_on_create=False,
        order=50,
    ),

    tabs.resource(
        key="family",
        label="Family",
        resource="employee-family",
        requires_record=True,
        show_on_create=False,
        order=60,
    ),

    tabs.resource(
        key="education",
        label="Education",
        resource="employee-education",
        requires_record=True,
        show_on_create=False,
        order=70,
    ),

    tabs.resource(
        key="experience",
        label="Experience",
        resource="employee-experience",
        requires_record=True,
        show_on_create=False,
        order=80,
    ),

    tabs.resource(
        key="certificate",
        label="Certificates",
        resource="employee-certificate",
        requires_record=True,
        show_on_create=False,
        order=90,
    ),

    # 
    tabs.resource(
        key="document",
        label="Documents",
        resource="employee-document",
        requires_record=True,
        show_on_create=False,
        order=100,
    ),

    tabs.resource(
        key="medical",
        label="Medical",
        resource="employee-medical",
        requires_record=True,
        show_on_create=False,
        order=110,
    ),


    tabs.resource(
        key="training",
        label="Training",
        resource="training",
        requires_record=True,
        show_on_create=False,
        order=140,
    ),

    tabs.history(
        key="history",
        label="History",
        component="EmployeesHistory",
        requires_record=True,
        show_on_create=False,
        order=150,
    ),

    tabs.custom(
        key="activity",
        label="Activity",
        component="EmployeesActivity",
        icon="activity",
        requires_record=True,
        show_on_create=False,
        order=160,
    ),
]