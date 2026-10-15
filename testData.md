1. Employee API
Positive case — Create employee successfully
Request:
{
  "emp_code": "EMP9020",
  "name": "Rahul Kumar",
  "email": "<rahul.kumar9020@gmail.com>",
  "department": "IT",
  "shift_start": "09:00",
  "shift_end": "18:00",
  "joined_on": "2026-10-01"
}

Expected response — 201 Created (example):
{
  "emp_code": "EMP9020",
  "name": "Rahul Kumar",
  "email": "<rahul.kumar9020@gmail.com>",
  "department": "IT",
  "shift_start": "09:00",
  "shift_end": "18:00",
  "joined_on": "2026-10-01"
}

Note: Adjust the field names to match your actual EmployeeCreate schema.
Negative case — Duplicate employee code
Send the same employee request again.
Expected response — 409 Conflict:
{
  "detail": "emp_code already exists"
}

Negative case — Invalid email
Request with an invalid email:
{
  "emp_code": "EMP9021",
  "name": "Rahul Kumar",
  "email": "invalid-email",
  "department": "IT",
  "shift_start": "09:00",
  "shift_end": "18:00",
  "joined_on": "2026-10-01"
}

Expected response — 422 Unprocessable Entity if your schema validates email format. FastAPI's error body typically contains a detail array describing the invalid field.

1. Attendance API
Positive case — Record attendance
Example request:
{
  "emp_code": "EMP9020",
  "punched_at": 1791968400000,
  "status": "PRESENT"
}

Expected response: a success status such as 200 OK or 201 Created, depending on your endpoint implementation.
Negative case — Employee code does not exist
{
  "emp_code": "EMP9999",
  "punched_at": 1791968400000,
  "status": "PRESENT"
}

Expected response: an error such as 404 Not Found if your API checks that the employee exists. The exact response depends on your code.
Negative case — Invalid status
{
  "emp_code": "EMP9020",
  "punched_at": 1791968400000,
  "status": "INVALID"
}

Expected response: 422 Unprocessable Entity if status is restricted to allowed values in your schema.

1. Regularization API
Positive case — Regularize attendance
{
  "reason": "Forgot to punch out due to an urgent meeting",
  "regularized_by": "HR001",
  "status": "PRESENT",
  "punch_in": 1791968400000,
  "punch_out": 1792000800000
}

Expected response: a success status such as 200 OK or 201 Created, depending on your endpoint.
Negative case — Missing reason
{
  "reason": "",
  "regularized_by": "HR001",
  "status": "PRESENT",
  "punch_in": 1791968400000,
  "punch_out": 1792000800000
}

Expected response: 422 only if your validation rules reject empty reasons. Otherwise, it may be accepted.
Negative case — Punch-out earlier than punch-in
{
  "reason": "Correction for attendance record",
  "regularized_by": "HR001",
  "status": "PRESENT",
  "punch_in": 1792000800000,
  "punch_out": 1791968400000
}

Expected response: a validation error only if your API enforces this time rule.
