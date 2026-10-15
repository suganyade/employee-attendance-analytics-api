# Employee Attendance & Analytics API

FastAPI + MongoDB implementation for HROne assignment contract v2.0.

## Requirements
- Python 3.11+ (Python 3.13 recommended)
- MongoDB 6.0+ reachable through `MONGO_URI`

## Setup (PowerShell)
```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --port 8000 --reload
```

Set `MONGO_URI` and `MONGO_DB` in `.env` or environment variables. Environment variables override `.env`.

Open http://127.0.0.1:8000/docs. `GET /health` returns `{"status":"ok"}` only when MongoDB responds.

## Notes
- The API uses `employees` and `attendance_logs` collections.
- Instants in request/response payloads are epoch milliseconds; stored instants are BSON UTC datetimes.
- Do not commit `.env`, secrets, a virtual environment, or data dumps.
- Test against MongoDB 6.0+; aggregation operators `$documents`, `$densify`, and `$setWindowFields` require a compatible server.
