from apps.framework.builders import importer


"""
Deklarasi fitur import Employee.

Endpoint preview/confirm/profile diturunkan otomatis dari `module`,
dan `preview_columns` harus sejajar dengan key yang dihasilkan
`EmployeeImporter.build_preview_row()`.
"""


EMPLOYEE_IMPORT_SCHEMA = importer.config(
    module="hr/employees",

    title="Import Employee",

    description=(
        "Import employee master data from CSV, including "
        "organization assignment, bank account, and education."
    ),

    completed_title="Employee Import Completed",

    completed_description=(
        "Employee records have been processed successfully."
    ),

    back_label="Back to Employees",
    back_route="/hr/employees",

    file_label="CSV File",

    preview_columns=[
        importer.column("row_number", "Row"),
        importer.column("employee_number", "Employee Number"),
        importer.column("display_name", "Name"),
        importer.column("nik", "NIK"),
        importer.column("company", "Company"),
        importer.column("department", "Department"),
        importer.column("position", "Position"),
        importer.column("bank_account_number", "Bank Account"),
        importer.column("education", "Education"),
        importer.column("action", "Action"),
    ],
)
