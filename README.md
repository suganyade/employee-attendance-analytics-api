# Employee Attendance & Analytics API

## Project Overview

The Employee Attendance & Analytics API is a backend application developed using Python, FastAPI, and MongoDB. It helps manage employee information, record attendance, handle attendance regularization, and retrieve attendance records based on date ranges.

The project provides RESTful APIs with request validation, error handling, and interactive API documentation through Swagger UI.

## Features

- Employee record management
- Employee attendance tracking
- Punch-in and punch-out time recording
- Attendance regularization with reasons
- Date-range filtering for attendance records
- Request data validation
- Duplicate record handling
- Interactive API documentation

## Technologies Used

- **Python** — Backend programming language
- **FastAPI** — REST API framework
- **MongoDB** — NoSQL database
- **PyMongo** — MongoDB integration
- **Pydantic** — Request data validation
- **Swagger UI** — API testing and documentation

## Project Structure

hr-attendance-api/
├── app/
│   └── main.py
├── requirements.txt
├── README.md
├── .gitignore
└── .env.example

*Note: Update the structure above if your project contains additional modules or different filenames.*

## Prerequisites

- Python installed
- MongoDB installed and running, or access to a MongoDB instance
- Git (optional, for cloning the repository)

## Installation and Setup

### 1. Clone the repository

bash
git clone YOUR_GITHUB_REPOSITORY_URL
cd hr-attendance-api

Replace `YOUR_GITHUB_REPOSITORY_URL` with your repository URL.

### 2. Create a virtual environment

bash
python -m venv .venv

Activate it on Windows PowerShell:

powershell
.\.venv\Scripts\Activate.ps1


### 3. Install dependencies

bash
pip install -r requirements.txt

### 4. Configure MongoDB

Create a `.env` file in the project root with your local MongoDB settings:

env
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db

Do not upload your `.env` file or any passwords or secrets to GitHub.

### 5. Run the application

bash
python -m uvicorn app.main:app --reload


If your FastAPI application uses a different module path, adjust the command accordingly.

## API Documentation

After starting the application, open:

- **Swagger UI:** http://127.0.0.1:8000/docs
- **ReDoc:** http://127.0.0.1:8000/redoc

Use Swagger UI to explore the available endpoints and test API requests and responses.

## Error Handling and Validation

The API uses request validation and appropriate HTTP error responses for supported error cases, such as invalid input and duplicate employee codes.

## Project Objective

The objective of this project is to provide a simple and reliable backend system for employee attendance management and to support attendance reporting through API-based access to stored records.

## Author

**Suganya Devi**

## License

This project was developed for educational and assignment purposes.

## Notes
- The API uses `employees` and `attendance_logs` collections.
- Instants in request/response payloads are epoch milliseconds; stored instants are BSON UTC datetimes.
- Do not commit `.env`, secrets, a virtual environment, or data dumps.
- Test against MongoDB 6.0+; aggregation operators `$documents`, `$densify`, and `$setWindowFields` require a compatible server.
