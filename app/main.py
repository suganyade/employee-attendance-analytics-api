"""HROne Employee Attendance & Analytics API (contract v2.0).

All instants are exposed as epoch milliseconds and stored as UTC BSON datetimes.
Calendar dates and shift times are IST strings. Analytics use MongoDB pipelines.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal, Optional, Annotated

from dotenv import load_dotenv # type: ignore
from fastapi import FastAPI, HTTPException, Query # type: ignore
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator # type: ignore
from pymongo import MongoClient, ASCENDING, DESCENDING, ReturnDocument # type: ignore
from pymongo.errors import DuplicateKeyError, PyMongoError # type: ignore
from pymongo.write_concern import WriteConcern # type: ignore

load_dotenv()  # os.environ values take precedence over .env values
UTC = timezone.utc
IST = timezone(timedelta(hours=5, minutes=30))
PRESENCE = {"PRESENT", "WFH", "ON_DUTY"}
STATUSES = {"PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"}
EPOCH_MIN, EPOCH_MAX = 100_000_000_000, 4_102_444_800_000

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")
client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"), serverSelectionTimeoutMS=2500, tz_aware=True)
db = client[os.getenv("MONGO_DB", "attendance_db")]
employees = db["employees"]
logs = db["attendance_logs"].with_options(write_concern=WriteConcern("majority"))

# ------------------------------- request models -------------------------------
class EmployeeCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = Field(default="09:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    shift_end: str = Field(default="18:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    joined_on: date

    @model_validator(mode="after")
    def distinct_shift_times(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start must differ from shift_end")
        return self

    @field_validator("name", "department")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("must not be blank")
        return value

class PunchInRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    emp_code: str
    punched_at: Optional[StrictInt] = None
    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"
    @field_validator("punched_at")
    @classmethod
    def valid_epoch(cls, value):
        if value is not None and not EPOCH_MIN <= value <= EPOCH_MAX:
            raise ValueError("must be epoch milliseconds in the supported range")
        return value

class PunchOutRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    emp_code: str
    punched_at: Optional[StrictInt] = None
    @field_validator("punched_at")
    @classmethod
    def valid_epoch(cls, value):
        if value is not None and not EPOCH_MIN <= value <= EPOCH_MAX:
            raise ValueError("must be epoch milliseconds in the supported range")
        return value

class RegularizeRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)
    status: Optional[Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]] = None
    punch_in: Optional[StrictInt] = None
    punch_out: Optional[StrictInt] = None
    @field_validator("punch_in", "punch_out")
    @classmethod
    def valid_epoch(cls, value):
        if value is not None and not EPOCH_MIN <= value <= EPOCH_MAX:
            raise ValueError("must be epoch milliseconds in the supported range")
        return value

# --------------------------------- primitives ---------------------------------
def to_dt(ms: int) -> datetime:
    # Truncate to whole seconds before storage/calculation (R1).
    return datetime.fromtimestamp(ms // 1000, tz=UTC)

def now_dt() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)

def epoch_ms(value: Optional[datetime]) -> Optional[int]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp()) * 1000

def round_half_up(value: float | Decimal, places: int = 2) -> float:
    quantum = Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))

def serialize_employee(doc: dict) -> dict:
    return {k: (epoch_ms(v) if k == "created_at" else v) for k, v in doc.items() if k != "_id"}

def serialize_record(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k != "_id"}
    for key in ("punch_in", "punch_out"):
        out[key] = epoch_ms(out.get(key))
    out.setdefault("work_hours", None)
    out.setdefault("late_minutes", 0)
    out.setdefault("overtime_minutes", 0)
    out.setdefault("half_day", False)
    history = []
    for item in out.get("history", []) or []:
        h = dict(item)
        h["at"] = epoch_ms(h.get("at"))
        changes = {}
        for field, pair in (h.get("changes") or {}).items():
            pair = dict(pair)
            if field in ("punch_in", "punch_out"):
                pair["from"] = epoch_ms(pair.get("from"))
                pair["to"] = epoch_ms(pair.get("to"))
            changes[field] = pair
        h["changes"] = changes
        history.append(h)
    out["history"] = history
    return out

def get_employee(emp_code: str) -> dict:
    employee = employees.find_one({"emp_code": emp_code})
    if not employee:
        raise HTTPException(404, "Employee not found")
    return employee

def get_record(emp_code: str, record_date: str) -> dict:
    doc = logs.find_one({"emp_code": emp_code, "date": record_date})
    if not doc:
        raise HTTPException(404, "Attendance record not found")
    return doc

def parse_month(month: str) -> tuple[date, date]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(422, "month must be YYYY-MM")
    y, m = map(int, month.split("-"))
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return start, end

def month_filter(month: str) -> tuple[str, str]:
    start, end = parse_month(month)
    return start.isoformat(), end.isoformat()

def attendance_date_and_late(punch: datetime, emp: dict) -> tuple[str, int]:
    local = punch.astimezone(IST)
    shift_start = datetime.strptime(emp["shift_start"], "%H:%M").time()
    shift_end = datetime.strptime(emp["shift_end"], "%H:%M").time()
    day = local.date()
    # For overnight shifts, early-morning punches belong to the previous shift day.
    if shift_end <= shift_start and local.time().replace(tzinfo=None) < shift_end:
        day -= timedelta(days=1)
    shift_start_dt = datetime.combine(day, shift_start, IST)
    elapsed = int((local - shift_start_dt).total_seconds() // 60)
    grace_elapsed = (local - shift_start_dt).total_seconds()
    late = elapsed if grace_elapsed > 600 else 0
    return day.isoformat(), max(0, late)

def shift_end_dt(attendance_day: str, emp: dict) -> datetime:
    d = date.fromisoformat(attendance_day)
    start_t = datetime.strptime(emp["shift_start"], "%H:%M").time()
    end_t = datetime.strptime(emp["shift_end"], "%H:%M").time()
    end_day = d + timedelta(days=1) if end_t <= start_t else d
    return datetime.combine(end_day, end_t, IST).astimezone(UTC).replace(microsecond=0)

def derived_fields(emp: dict, attendance_day: str, status: str, punch_in: Optional[datetime], punch_out: Optional[datetime]) -> dict:
    if status not in PRESENCE:
        return {"work_hours": None, "late_minutes": 0, "overtime_minutes": 0, "half_day": False}
    late = attendance_date_and_late(punch_in, emp)[1] if punch_in else 0
    work_hours = None
    overtime = 0
    half = False
    if punch_in and punch_out:
        seconds = (punch_out - punch_in).total_seconds()
        work_hours = round_half_up(seconds / 3600, 2)
        mins_after_shift = int((punch_out - shift_end_dt(attendance_day, emp)).total_seconds() // 60)
        overtime = max(0, mins_after_shift) if mins_after_shift >= 30 else 0
        half = work_hours < 4.50
    return {"work_hours": work_hours, "late_minutes": late, "overtime_minutes": overtime, "half_day": half}

def working_days_pipeline(joined_field: str, start: date, end: date) -> list:
    """Aggregation expression counting Mon-Fri in [max(joined_on,start), end)."""
    return [{"$set": {"_wd_start": {"$max": [f"${joined_field}", start.isoformat()]}}},
            {"$set": {"_wd_dates": {"$map": {"input": {"$range": [0, {"$max": [0, {"$dateDiff": {"startDate": {"$dateFromString": {"dateString": "$_wd_start"}}, "endDate": {"$dateFromString": {"dateString": end.isoformat()}}, "unit": "day"}}]}]}, "as": "i", "in": {"$dateAdd": {"startDate": {"$dateFromString": {"dateString": "$_wd_start"}}, "unit": "day", "amount": "$$i"}}}}}},
            {"$set": {"working_days": {"$size": {"$filter": {"input": "$_wd_dates", "as": "d", "cond": {"$and": [{"$gte": [{"$dayOfWeek": "$$d"}, 2]}, {"$lte": [{"$dayOfWeek": "$$d"}, 6]}]}}}}}},
            {"$unset": ["_wd_start", "_wd_dates"]}]

# ----------------------------------- startup -----------------------------------
@app.on_event("startup")
def ensure_indexes():
    # Idempotent indexes; unique keys also provide race safety for create/punch-in.
    employees.create_index([("emp_code", ASCENDING)], unique=True, name="uq_employee_code")
    employees.create_index([("department", ASCENDING), ("joined_on", ASCENDING)], name="department_joined")
    logs.create_index([("emp_code", ASCENDING), ("date", ASCENDING)], unique=True, name="uq_attendance_employee_date")
    logs.create_index([("date", DESCENDING), ("emp_code", ASCENDING)], name="attendance_date_employee")
    logs.create_index([("emp_code", ASCENDING), ("date", ASCENDING), ("status", ASCENDING)], name="attendance_employee_date_status")
    logs.create_index([("date", ASCENDING), ("status", ASCENDING), ("late_minutes", DESCENDING)], name="attendance_month_status_late")
    logs.create_index([("punch_in", DESCENDING), ("emp_code", ASCENDING)], name="attendance_punch_in")

# ----------------------------------- health ------------------------------------
@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}
    except PyMongoError:
        raise HTTPException(503, "MongoDB unavailable")

#
@app.post("/employees", status_code=201)
def create_employee(payload: EmployeeCreate):
    doc = payload.model_dump()
    doc["joined_on"] = payload.joined_on.isoformat()
    doc["created_at"] = now_dt()

    # Check employee code explicitly
    if employees.find_one({"emp_code": doc["emp_code"]}):
        raise HTTPException(
            status_code=409,
            detail="emp_code already exists"
        )

    # Check email explicitly
    if employees.find_one({"email": doc["email"]}):
        raise HTTPException(
            status_code=409,
            detail="email already exists"
        )

    try:
        employees.insert_one(doc)
    except DuplicateKeyError as exc:
        # Handles duplicates caused by a concurrent request or another unique index
        raise HTTPException(
            status_code=409,
            detail="Duplicate employee field; check emp_code and email"
        ) from exc

    return serialize_employee(doc)


@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    filt = {"department": department} if department is not None else {}
    total = employees.count_documents(filt)
    cursor = employees.find(filt, {"_id": 0}).sort("emp_code", ASCENDING).skip((page - 1) * page_size).limit(page_size)
    return {"items": [serialize_employee(x) for x in cursor], "total": total, "page": page, "page_size": page_size}

# ---------------------------------- attendance ---------------------------------
@app.post("/attendance/punch-in", status_code=201)
def punch_in(payload: PunchInRequest):
    emp = get_employee(payload.emp_code)
    stamp = to_dt(payload.punched_at) if payload.punched_at is not None else now_dt()
    day, late = attendance_date_and_late(stamp, emp)
    doc = {"emp_code": payload.emp_code, "date": day, "status": payload.status,
           "punch_in": stamp, "punch_out": None, "work_hours": None, "late_minutes": late,
           "overtime_minutes": 0, "half_day": False, "history": []}
    try:
        logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "Attendance record already exists for this employee and date")
    return serialize_record(doc)

@app.post("/attendance/punch-out")
def punch_out(payload: PunchOutRequest):
    emp = get_employee(payload.emp_code)
    stamp = to_dt(payload.punched_at) if payload.punched_at is not None else now_dt()
    # Most recent open shift whose punch-in is not after this punch-out; supports overnight shifts.
    rec = logs.find_one({"emp_code": payload.emp_code, "punch_in": {"$ne": None, "$lte": stamp}, "punch_out": None}, sort=[("punch_in", DESCENDING), ("date", DESCENDING)])
    if rec is None:
        prior = logs.find_one({"emp_code": payload.emp_code, "punch_in": {"$ne": None, "$lte": stamp}}, sort=[("punch_in", DESCENDING)])
        if prior and prior.get("punch_out") is not None:
            raise HTTPException(409, "That attendance record is already punched out")
        raise HTTPException(404, "No open punch-in found")
    pin = rec["punch_in"]
    seconds = (stamp - pin).total_seconds()
    if seconds <= 0 or seconds > 24 * 3600:
        raise HTTPException(422, "punched_at must be after punch_in and within 24 hours")
    derived = derived_fields(emp, rec["date"], rec["status"], pin, stamp)
    updated = logs.find_one_and_update(
        {"emp_code": payload.emp_code, "date": rec["date"], "punch_out": None},
        {"$set": {"punch_out": stamp, **derived}}, return_document=ReturnDocument.AFTER)
    if updated is None:
        raise HTTPException(409, "Attendance record was punched out concurrently")
    return serialize_record(updated)

@app.get("/attendance")
def list_attendance(emp_code: Optional[str] = None, date_from: Optional[date] = None, date_to: Optional[date] = None,
                    status: Optional[Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]] = None,
                    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must be on or before date_to")
    filt = {}
    if emp_code is not None: filt["emp_code"] = emp_code
    if status is not None: filt["status"] = status
    if date_from or date_to:
        filt["date"] = {}
        if date_from: filt["date"]["$gte"] = date_from.isoformat()
        if date_to: filt["date"]["$lte"] = date_to.isoformat()
    total = logs.count_documents(filt)
    cursor = logs.find(filt).sort([("date", DESCENDING), ("emp_code", ASCENDING)]).skip((page - 1) * page_size).limit(page_size)
    return {"items": [serialize_record(x) for x in cursor], "total": total, "page": page, "page_size": page_size}

@app.patch("/attendance/{emp_code}/{record_date}")
def regularize_attendance(emp_code: str, record_date: date, payload: RegularizeRequest):
    emp = get_employee(emp_code)
    day = record_date.isoformat()
    old = get_record(emp_code, day)
    status = payload.status if payload.status is not None else old["status"]
    if status in {"ABSENT", "LEAVE"}:
        if payload.punch_in is not None or payload.punch_out is not None:
            raise HTTPException(422, "ABSENT and LEAVE cannot have punch times")
        pin = pout = None
    else:
        pin = to_dt(payload.punch_in) if payload.punch_in is not None else old.get("punch_in")
        pout = to_dt(payload.punch_out) if payload.punch_out is not None else old.get("punch_out")
        if pin is None:
            raise HTTPException(422, "Presence status requires punch_in")
        actual_day, _ = attendance_date_and_late(pin, emp)
        if actual_day != day:
            raise HTTPException(422, "punch_in must belong to the record attendance date")
        if pout is not None and ((pout - pin).total_seconds() <= 0 or (pout - pin).total_seconds() > 86400):
            raise HTTPException(422, "punch_out must be after punch_in and within 24 hours")
    derived = derived_fields(emp, day, status, pin, pout)
    proposed = {"status": status, "punch_in": pin, "punch_out": pout, **derived}
    changed = {}
    for field, new_value in proposed.items():
        old_value = old.get(field)
        if field in ("late_minutes", "overtime_minutes"):
            old_value = old.get(field, 0)
        if field == "half_day": old_value = old.get(field, False)
        if old_value != new_value:
            if field in ("punch_in", "punch_out"):
                changed[field] = {"from": old_value, "to": new_value}
            else:
                changed[field] = {"from": old_value, "to": new_value}
    if not changed:
        raise HTTPException(422, "Request does not change the record")
    at = now_dt()
    entry = {"at": at, "by": payload.regularized_by, "reason": payload.reason, "changes": changed}
    # Compare-and-set guards against lost updates; $push is atomic and history is never overwritten.
    expected = {"emp_code": emp_code, "date": day}
    for field in proposed:
        if field in old:
            expected[field] = old[field]
        else:
            expected[field] = {"$exists": False}
    update = {"$set": proposed, "$push": {"history": entry}}
    updated = logs.find_one_and_update(expected, update, return_document=ReturnDocument.AFTER)
    if updated is None:
        raise HTTPException(409, "Attendance record changed concurrently; retry the correction")
    return serialize_record(updated)

# ----------------------------------- analytics ---------------------------------
@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str):
    emp = get_employee(emp_code)
    start, end = parse_month(month)
    match = {"emp_code": emp_code, "date": {"$gte": start.isoformat(), "$lt": end.isoformat()}}
    pipeline = [{"$match": match},
        {"$addFields": {"_day": {"$dateFromString": {"dateString": "$date"}}, "_late": {"$ifNull": ["$late_minutes", 0]}, "_ot": {"$ifNull": ["$overtime_minutes", 0]}, "_half": {"$ifNull": ["$half_day", False]}}},
        {"$group": {"_id": None,
            "present_days": {"$sum": {"$cond": [{"$and": [{"$in": ["$status", list(PRESENCE)]}, {"$gte": [{"$dayOfWeek": "$_day"}, 2]}, {"$lte": [{"$dayOfWeek": "$_day"}, 6]}]}, {"$cond": ["$_half", 0.5, 1]}, 0]}},
            "leave_days": {"$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}},
            "late_count": {"$sum": {"$cond": [{"$gt": ["$_late", 0]}, 1, 0]}},
            "total_late_minutes": {"$sum": "$_late"}, "total_overtime_minutes": {"$sum": "$_ot"}}}]
    rows = list(logs.aggregate(pipeline))
    metrics = rows[0] if rows else {}
    # Working-day count is generated in MongoDB as a date range, not by loading logs into Python.
    wd_pipe = [{"$documents": [{"joined_on": max(emp["joined_on"], start.isoformat())}]},
               {"$set": {"dates": {"$map": {"input": {"$range": [0, {"$dateDiff": {"startDate": {"$dateFromString": {"dateString": "$joined_on"}}, "endDate": {"$dateFromString": {"dateString": end.isoformat()}}, "unit": "day"}}]}, "as": "i", "in": {"$dateAdd": {"startDate": {"$dateFromString": {"dateString": "$joined_on"}}, "unit": "day", "amount": "$$i"}}}}}},
               {"$project": {"working_days": {"$size": {"$filter": {"input": "$dates", "as": "d", "cond": {"$and": [{"$gte": [{"$dayOfWeek": "$$d"}, 2]}, {"$lte": [{"$dayOfWeek": "$$d"}, 6]}]}}}}}}]
    wd_result = list(db.aggregate(wd_pipe))
    working_days = wd_result[0]["working_days"] if wd_result else 0
    present = round_half_up(metrics.get("present_days", 0), 2)
    pct = round_half_up(present / working_days * 100, 4) if working_days else None
    return {"emp_code": emp_code, "month": month, "working_days": working_days, "present_days": present,
            "leave_days": metrics.get("leave_days", 0), "late_count": metrics.get("late_count", 0),
            "total_late_minutes": metrics.get("total_late_minutes", 0), "total_overtime_minutes": metrics.get("total_overtime_minutes", 0), "attendance_pct": pct}

@app.get("/analytics/departments/summary")
def department_summary(month: str, department: Optional[str] = None):
    start, end = month_filter(month)
    emp_match = {"joined_on": {"$lt": end}}
    if department is not None: emp_match["department"] = department
    pipeline = [{"$match": emp_match},
        {"$lookup": {"from": "attendance_logs", "let": {"code": "$emp_code"}, "pipeline": [{"$match": {"$expr": {"$and": [{"$eq": ["$emp_code", "$$code"]}, {"$gte": ["$date", start]}, {"$lt": ["$date", end]}]}}}, {"$addFields": {"_day": {"$dateFromString": {"dateString": "$date"}}, "_half": {"$ifNull": ["$half_day", False]}, "_late": {"$ifNull": ["$late_minutes", 0]}}}], "as": "month_logs"}},
        {"$unwind": {"path": "$month_logs", "preserveNullAndEmptyArrays": True}},
        {"$group": {"_id": "$department", "headcount": {"$addToSet": "$emp_code"},
            "present_days": {"$sum": {"$cond": [{"$and": [{"$in": ["$month_logs.status", list(PRESENCE)]}, {"$gte": [{"$dayOfWeek": "$month_logs._day"}, 2]}, {"$lte": [{"$dayOfWeek": "$month_logs._day"}, 6]}]}, {"$cond": ["$month_logs._half", 0.5, 1]}, 0]}},
            "hours_sum": {"$sum": {"$cond": [{"$and": [{"$in": ["$month_logs.status", list(PRESENCE)]}, {"$ne": ["$month_logs.work_hours", None]}]}, "$month_logs.work_hours", 0]}},
            "hours_n": {"$sum": {"$cond": [{"$and": [{"$in": ["$month_logs.status", list(PRESENCE)]}, {"$ne": ["$month_logs.work_hours", None]}]}, 1, 0]}},
            "late_count": {"$sum": {"$cond": [{"$gt": ["$month_logs._late", 0]}, 1, 0]}}, "total_late_minutes": {"$sum": "$month_logs._late"},
            "leave_count": {"$sum": {"$cond": [{"$eq": ["$month_logs.status", "LEAVE"]}, 1, 0]}},
            "on_duty_count": {"$sum": {"$cond": [{"$eq": ["$month_logs.status", "ON_DUTY"]}, 1, 0]}}}},
        {"$set": {
            "headcount": {"$size": "$headcount"},
            "avg_work_hours": {"$cond": [
                {"$gt": ["$hours_n", 0]},
                {"$divide": [{"$floor": {"$add": [{"$multiply": [{"$divide": ["$hours_sum", "$hours_n"]}, 100]}, 0.5]}}, 100]},
                None,
            ]},
        }},
        {"$match": {"headcount": {"$gt": 0}}}, {"$sort": {"_id": 1}},
        {"$project": {"_id": 0, "department": "$_id", "headcount": 1, "present_days": 1, "avg_work_hours": 1, "late_count": 1, "total_late_minutes": 1, "leave_count": 1, "on_duty_count": 1}}]
    # The aggregation's avg uses half-up arithmetic above to avoid banker's rounding.
    return {"month": month, "items": list(employees.aggregate(pipeline))}

@app.get("/analytics/leaderboard/late")
def late_leaderboard(month: str, limit: int = Query(10, ge=1, le=50), department: Optional[str] = None):
    start, end = month_filter(month)
    pipeline = [{"$match": {"date": {"$gte": start, "$lt": end}, "late_minutes": {"$gt": 0}}},
        {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": {"$ifNull": ["$late_minutes", 0]}}, "late_count": {"$sum": 1}}},
        {"$lookup": {"from": "employees", "localField": "_id", "foreignField": "emp_code", "as": "employee"}}, {"$unwind": "$employee"}]
    if department is not None:
        pipeline.append({"$match": {"employee.department": department}})
    pipeline += [{"$setWindowFields": {"sortBy": {"total_late_minutes": -1}, "output": {"rank": {"$rank": {}}}}},
        {"$match": {"rank": {"$lte": limit}}}, {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {"$project": {"_id": 0, "rank": 1, "emp_code": "$_id", "name": "$employee.name", "department": "$employee.department", "total_late_minutes": 1, "late_count": 1}}]
    return {"month": month, "items": list(logs.aggregate(pipeline))}

@app.get("/analytics/departments/{department}/trend")
def department_trend(department: str, from_date: date = Query(..., alias="from"), to: date = Query(...)):
    if to < from_date:
        raise HTTPException(422, "to must be on or after from")
    if (to - from_date).days + 1 > 92:
        raise HTTPException(422, "date range must not exceed 92 days")
    if employees.count_documents({"department": department}) == 0:
        raise HTTPException(404, "Unknown department")
    start_dt = datetime.combine(from_date, time.min, UTC)
    end_exclusive = datetime.combine(to + timedelta(days=1), time.min, UTC)
    pipeline = [
        {"$documents": [{"_day": start_dt}]},
        {"$densify": {"field": "_day", "range": {"step": 1, "unit": "day", "bounds": [start_dt, end_exclusive]}}},
        {"$set": {"_date": {"$dateToString": {"date": "$_day", "format": "%Y-%m-%d", "timezone": "UTC"}}}},
        {"$lookup": {"from": "attendance_logs", "let": {"day": "$_date"}, "pipeline": [
            {"$match": {"$expr": {"$eq": ["$date", "$$day"]}}},
            {"$lookup": {"from": "employees", "localField": "emp_code", "foreignField": "emp_code", "as": "e"}},
            {"$unwind": "$e"}, {"$match": {"e.department": department}},
            {"$project": {"status": 1, "late_minutes": 1, "half_day": 1}}], "as": "day_logs"}},
        {"$lookup": {"from": "employees", "let": {"day": "$_date"}, "pipeline": [
            {"$match": {"$expr": {"$and": [{"$eq": ["$department", department]}, {"$lte": ["$joined_on", "$$day"]}]}}},
            {"$count": "n"}], "as": "hc"}},
        {"$set": {
            "is_working_day": {"$and": [{"$gte": [{"$dayOfWeek": "$_day"}, 2]}, {"$lte": [{"$dayOfWeek": "$_day"}, 6]}]},
            "headcount": {"$ifNull": [{"$arrayElemAt": ["$hc.n", 0]}, 0]},
            "present_count": {"$sum": {"$map": {"input": "$day_logs", "as": "r", "in": {"$cond": [{"$in": ["$$r.status", list(PRESENCE)]}, {"$cond": [{"$ifNull": ["$$r.half_day", False]}, 0.5, 1]}, 0]}}}},
            "late_count": {"$size": {"$filter": {"input": "$day_logs", "as": "r", "cond": {"$gt": [{"$ifNull": ["$$r.late_minutes", 0]}, 0]}}}},
        }},
        {"$set": {"attendance_rate": {"$cond": [{"$and": ["$is_working_day", {"$gt": ["$headcount", 0]}]}, {"$divide": [{"$floor": {"$add": [{"$multiply": [{"$divide": ["$present_count", "$headcount"]}, 10000]}, 0.5]}}, 10000]}, None]}}},
        {"$setWindowFields": {"sortBy": {"_day": 1}, "output": {"_ma_raw": {"$avg": "$attendance_rate", "window": {"documents": [-6, 0]}}}}},
        {"$set": {"moving_avg_7d": {"$cond": [{"$ne": ["$_ma_raw", None]}, {"$divide": [{"$floor": {"$add": [{"$multiply": ["$_ma_raw", 10000]}, 0.5]}}, 10000]}, None]}}},
        {"$sort": {"_day": 1}},
        {"$project": {"_id": 0, "date": "$_date", "is_working_day": 1, "headcount": 1, "present_count": 1, "late_count": 1, "attendance_rate": 1, "moving_avg_7d": 1}},
    ]
    # db.aggregate is used because $documents must be the first stage.
    return {"department": department, "items": list(db.aggregate(pipeline))}

# ------------------------------- explain endpoint ------------------------------
def explain_find(filter_doc: dict, sort_doc: dict, skip: int, limit: int) -> dict:
    cmd = {"find": "attendance_logs", "filter": filter_doc, "sort": sort_doc, "skip": skip, "limit": limit}
    return db.command({"explain": cmd, "verbosity": "executionStats"})

def explain_aggregate(collection: str, pipeline: list) -> dict:
    return db.command({"explain": {"aggregate": collection, "pipeline": pipeline, "cursor": {}}, "verbosity": "executionStats"})

@app.get("/admin/explain/{endpoint}")
def explain_endpoint(endpoint: Literal["attendance_list", "employee_monthly", "department_summary", "late_leaderboard", "department_trend"],
                     emp_code: Optional[str] = None, month: Optional[str] = None, department: Optional[str] = None,
                     limit: int = Query(10, ge=1, le=50), date_from: Optional[date] = None, date_to: Optional[date] = None,
                     status: Optional[Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]] = None,
                     from_date: Optional[date] = Query(None, alias="from"), to: Optional[date] = None,
                     page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    if endpoint == "attendance_list":
        if date_from and date_to and date_from > date_to: raise HTTPException(422, "date_from must be on or before date_to")
        filt = {}
        if emp_code is not None: filt["emp_code"] = emp_code
        if status is not None: filt["status"] = status
        if date_from or date_to:
            filt["date"] = {}
            if date_from: filt["date"]["$gte"] = date_from.isoformat()
            if date_to: filt["date"]["$lte"] = date_to.isoformat()
        exp = explain_find(filt, {"date": -1, "emp_code": 1}, (page-1)*page_size, page_size)
        return {"endpoint": endpoint, "collection": "attendance_logs", "explain": exp}
    if endpoint == "department_trend":
        if department is None or from_date is None or to is None:
            raise HTTPException(422, "department, from, and to are required")
        if to < from_date or (to - from_date).days + 1 > 92:
            raise HTTPException(422, "Invalid department trend date range")
        # Keep the explained scan bounded by the same date range used by the trend pipeline.
        pipeline = [{"$match": {"date": {"$gte": from_date.isoformat(), "$lte": to.isoformat()}}}, {"$group": {"_id": "$date", "count": {"$sum": 1}}}]
        exp = explain_aggregate("attendance_logs", pipeline)
        return {"endpoint": endpoint, "collection": "attendance_logs", "explain": exp}
    if month is None: raise HTTPException(422, "month is required for this endpoint")
    start, end = month_filter(month)
    if endpoint == "employee_monthly":
        if emp_code is None: raise HTTPException(422, "emp_code is required")
        get_employee(emp_code)
        pipeline = [{"$match": {"emp_code": emp_code, "date": {"$gte": start, "$lt": end}}}, {"$group": {"_id": "$emp_code", "count": {"$sum": 1}}}]
        exp = explain_aggregate("attendance_logs", pipeline)
        return {"endpoint": endpoint, "collection": "attendance_logs", "explain": exp}
    if endpoint == "department_summary":
        pipeline = [{"$match": {"date": {"$gte": start, "$lt": end}}}, {"$group": {"_id": "$emp_code", "count": {"$sum": 1}}}]
        exp = explain_aggregate("attendance_logs", pipeline)
        return {"endpoint": endpoint, "collection": "attendance_logs", "explain": exp}
    if endpoint == "late_leaderboard":
        pipeline = [{"$match": {"date": {"$gte": start, "$lt": end}, "late_minutes": {"$gt": 0}}}, {"$group": {"_id": "$emp_code", "total": {"$sum": "$late_minutes"}}}]
        exp = explain_aggregate("attendance_logs", pipeline)
        return {"endpoint": endpoint, "collection": "attendance_logs", "explain": exp}
    raise HTTPException(422, "Unsupported endpoint")
