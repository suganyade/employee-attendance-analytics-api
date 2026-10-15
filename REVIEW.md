# REVIEW.md

**Review limitation:** The uploaded candidate kit did not include the original starter `app/main.py`; therefore I cannot honestly claim to have verified specific defects in that original file. The implementation in this repository was written against `openapi.yaml` and `DATA_MODEL.md`, rather than a line-by-line patch of the absent starter.

| # | Where | What is wrong | How to notice | Fix in this implementation |
|---|---|---|---|---|
| 1 | Employee identity | MongoDB `_id` must not be used as the business identifier. | Create/list an employee and inspect response. | Uses `emp_code` and omits `_id` from responses. |
| 2 | Punch-in concurrency | Check-then-insert can create duplicates under concurrent requests. | Send parallel punch-ins for same employee/date. | Unique `(emp_code,date)` index; duplicate-key maps to 409. |
| 3 | Punch-out concurrency | A read followed by an unconditional update can let two requests both succeed. | Send simultaneous punch-outs. | Conditional `find_one_and_update` only closes an open record. |
| 4 | Time conversion | API instants are epoch milliseconds, not ISO strings or seconds. | Submit seconds, floats, strings, or out-of-range values. | Strict integer validation and UTC datetime conversion. |
| 5 | Time-zone handling | Attendance date and shift calculations must use IST, including overnight shifts. | Punch around midnight for an overnight shift. | Uses IST for attendance-day and shift calculations. |
| 6 | Rounding | Python's default `round` uses ties-to-even. | Test a half-cent work-hour value. | Uses `Decimal` with `ROUND_HALF_UP` for computed work hours. |
| 7 | Analytics source | Analytics must use stored derived fields, not silently recalculate seeded values. | Seed a record with derived values differing from punch times. | Monthly and department analytics aggregate stored fields. |
| 8 | Audit history | Corrections must append one immutable history entry with changed fields only. | Correct one field and inspect `history`. | Uses atomic `$push` and compare-and-set update. |
| 9 | Pagination | Page size and total must follow R10. | Request page 2 with a filter. | Uses 1-based pagination, max page size 100, and filtered count. |
| 10 | Empty trend days | Returning only days with logs loses missing weekdays/weekends. | Query a date range with no logs. | Trend pipeline seeds a calendar day and uses `$densify`. |

The checks above describe contract risks addressed in the new implementation. They are not represented as confirmed defects in the missing original starter.
