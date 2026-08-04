# app/core/permissions.py

# Master dictionary of all available permissions in the system.
# Grouped by category for the frontend UI to render sections.
PERMISSION_CATEGORIES = {
    "Dashboard & General": [
        {"key": "view_dashboard", "label": "View Dashboard"},
    ],
    "Client Management": [
        {"key": "view_clients", "label": "View Clients"},
        {"key": "manage_clients", "label": "Create, Edit & Archive Clients"},
    ],
    "Fleet & Vehicles": [
        {"key": "view_vehicles", "label": "View Fleet"},
        {"key": "manage_vehicles", "label": "Add, Edit & Retire Vehicles"},
        {"key": "manage_maintenance", "label": "Manage Maintenance & Service Logs"},
    ],
    "Bookings & Contracts": [
        {"key": "view_bookings", "label": "View Bookings Calendar"},
        {"key": "manage_bookings", "label": "Create & Manage Bookings"},
        {"key": "view_contracts", "label": "View Contracts"},
        {"key": "manage_contracts", "label": "Generate & Sign Contracts"},
    ],
    "Financials": [
        {"key": "view_financials", "label": "View Invoices & Payments"},
        {"key": "record_payments", "label": "Record Payments"},
        {"key": "view_reports", "label": "View Financial Reports"},
    ],
    "Team & Settings": [
        {"key": "view_team", "label": "View Team Members"},
        {"key": "manage_team", "label": "Manage Team (Invite, Suspend, Delete)"},
        {"key": "manage_settings", "label": "Manage Agency Settings & Policies"},
    ],
}

# A flat list of all permission keys for easy validation
ALL_PERMISSION_KEYS = [
    perm["key"] for category in PERMISSION_CATEGORIES.values() for perm in category
]
