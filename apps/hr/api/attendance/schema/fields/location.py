from apps.framework.builders import field


LOCATION_FIELDS = {
    "check_in_latitude": field.number(
        tab="location",
        label="Check In Latitude",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=10,
    ),

    "check_in_longitude": field.number(
        tab="location",
        label="Check In Longitude",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=20,
    ),

    "check_out_latitude": field.number(
        tab="location",
        label="Check Out Latitude",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=30,
    ),

    "check_out_longitude": field.number(
        tab="location",
        label="Check Out Longitude",
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=40,
    ),

    "check_in_address": field.textarea(
        tab="location",
        label="Check In Address",
        rows=2,
        layout="full",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=50,
    ),

    "check_out_address": field.textarea(
        tab="location",
        label="Check Out Address",
        rows=2,
        layout="full",
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=60,
    ),

    "is_geofence_valid": field.boolean(
        tab="location",
        label="Geofence Valid",
        default=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        placement="quick",
        order=70,
    ),
}