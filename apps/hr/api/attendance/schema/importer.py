from apps.framework.builders import importer


"""
Deklarasi fitur import Attendance.

`preview_columns` harus sejajar dengan key yang dihasilkan
`AttendanceImporter.build_preview_row()`.
"""


ATTENDANCE_IMPORT_SCHEMA = importer.config(
    module="hr/attendance",

    title="Import Attendance",

    description=(
        "Import attendance taps from any machine format. The selected "
        "Import Profile describes the file; machine IDs are resolved "
        "through Attendance Device Employee Mapping, and work date, "
        "schedule, and shift come from HR — never from the file."
    ),

    completed_title="Attendance Import Completed",

    completed_description=(
        "Attendance records have been processed successfully."
    ),

    back_label="Back to Attendance",
    back_route="/hr/attendance",

    file_label="CSV File",

    preview_columns=[
        importer.column("row_number", "Row", width=70),
        importer.column("raw_employee_id", "Raw Employee ID"),
        importer.column("employee_code", "Employee Number"),
        importer.column("employee_name", "Employee Name"),
        importer.column("raw_timestamp", "Raw Timestamp"),
        importer.column("log_time", "Normalized Timestamp"),
        importer.column("work_date", "Work Date"),
        importer.column("schedule_label", "Schedule / Shift"),
        importer.column("log_type", "Event"),
        importer.column("device_code", "Device"),
        importer.column("status_label", "Status"),
        importer.column("message", "Message"),
    ],
)
