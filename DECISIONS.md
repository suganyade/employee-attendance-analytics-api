# DECISIONS.md

1. **Indexes.** A unique `employees.emp_code` index makes employee identity immutable in practice and makes concurrent duplicate creates conflict. A unique `(emp_code, date)` index enforces one attendance record per employee per attendance day and is the key protection against simultaneous punch-ins. Date-first and employee/date/status indexes support the sorted attendance list and common filtered lookups. Department/join-date supports headcount and trend lookups. The punch-in index helps find the latest open record for punch-out. I would measure index size and write overhead before adding more compound indexes.

2. **Punch-in race.** Both requests can reach the insert, but MongoDB's unique `(emp_code, date)` index allows only one insert. The winner returns 201; the duplicate-key loser returns 409. A pre-check alone would not be safe.

3. **Ties.** The leaderboard uses MongoDB `$rank` over total late minutes. Equal totals share a rank and the next rank is skipped. `limit` is applied to rank, not row count, so all tied employees whose rank is within the limit are returned; rows then sort by minutes and `emp_code`.

4. **Headcount.** Department summary starts from employees who joined by the month's end and looks up that employee's logs. Employees without logs remain in the pipeline and count toward headcount.

5. **100x data.** I would inspect explain plans and production query metrics, partition/archive old logs by retention policy, and consider pre-aggregated daily metrics if live aggregation became too costly.
