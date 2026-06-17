MANAGE_ROLES = frozenset({"owner", "admin"})
JOIN_REQUEST_ROLES = frozenset({"teacher", "lecturer", "professor", "student"})
STAFF_ROLES = frozenset({"owner", "admin", "principal", "teacher", "lecturer", "professor"})
TEACHING_STAFF_ROLES = frozenset({"principal", "teacher", "lecturer", "professor"})
TEACHER_ROLES = frozenset({"owner", "admin", "principal", "teacher", "lecturer", "professor"})
VIEW_DIRECTORY_ROLES = STAFF_ROLES

STAFF_MANAGEABLE_ROLES = frozenset({"admin", "principal", "teacher", "lecturer", "professor"})
STUDENT_ROLE = "student"
ALL_ASSIGNABLE_ROLES = STAFF_MANAGEABLE_ROLES | {STUDENT_ROLE}

ROLE_LABELS = {
    "owner": "Owner",
    "admin": "Admin",
    "principal": "Principal",
    "teacher": "Teacher",
    "lecturer": "Lecturer",
    "professor": "Professor",
    "student": "Student",
}
