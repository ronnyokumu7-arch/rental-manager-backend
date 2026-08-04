# Rental Manager Backend

A comprehensive FastAPI-based backend application for managing vehicle rental operations, including tenant management, bookings, contracts, payments, invoices, and subscription handling.

## 📋 Table of Contents

- [Overview](#overview)
- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation & Setup](#installation--setup)
- [Environment Configuration](#environment-configuration)
- [Database Migrations](#database-migrations)
- [Running the Application](#running-the-application)
- [API Documentation](#api-documentation)
- [Authentication & Authorization](#authentication--authorization)
- [Project Features](#project-features)
- [Background Jobs](#background-jobs)
- [Contributing](#contributing)

## 🎯 Overview

Rental Manager Backend is a production-ready REST API designed to manage multi-tenant vehicle rental businesses. It provides complete functionality for:

- **Tenant Management**: Support for multiple independent rental businesses
- **Client Management**: Track clients with contact info, driver's licenses, and communication history
- **Vehicle Management**: Manage vehicle fleet with detailed specifications
- **Bookings & Contracts**: Create and manage rental agreements with PDF generation
- **Payment Processing**: Track payments with multiple payment methods
- **Invoicing**: Automated invoice generation and tracking
- **Subscriptions**: Flexible subscription plans with usage tracking
- **Reporting**: Comprehensive reports for business analytics
- **User Management**: Role-based access control (RBAC) with multiple permission levels

## ✨ Key Features

### Core Business Features
- 🚗 **Vehicle Fleet Management** - Full lifecycle management of rental vehicles
- 📅 **Booking System** - Create, update, and manage rental bookings
- 📝 **Contract Management** - Generate and track rental contracts with PDF export
- 💰 **Payment Tracking** - Record and manage payments with multiple payment methods
- 📊 **Invoice Management** - Automated invoice creation and delivery
- 📈 **Reporting** - Business metrics, revenue reports, and utilization analytics
- 🔄 **Subscription Plans** - Flexible subscription tiers with automated billing

### Technical Features
- 🔐 **JWT Authentication** - Secure token-based authentication with refresh tokens
- 🛡️ **Role-Based Access Control (RBAC)** - Fine-grained permission system
- 👥 **Multi-Tenant Architecture** - Isolated data per tenant with shared infrastructure
- 📧 **Email Integration** - Automated email notifications via Resend
- 🗄️ **Database Migrations** - Version-controlled schema changes with Alembic
- ⏰ **Job Scheduling** - Background job processing for subscriptions and bookings
- 🔄 **CORS Support** - Pre-configured for multiple frontend origins
- 📄 **PDF Generation** - Contract and invoice generation with ReportLab

## 🛠️ Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| **Framework** | FastAPI | 0.136.3 |
| **Database** | PostgreSQL | (via psycopg2) |
| **ORM** | SQLAlchemy | 2.0.50 |
| **Migrations** | Alembic | 1.18.4 |
| **Authentication** | JWT + Bcrypt | PyJWT, bcrypt 4.0.1 |
| **Validation** | Pydantic | 2.13.4 |
| **Server** | Uvicorn | 0.48.0 |
| **Job Scheduling** | APScheduler | - |
| **Email** | Resend API | - |
| **PDF Generation** | ReportLab | - |
| **Excel** | OpenPyXL | - |

## 📁 Project Structure

```
rental-manager-backend/
├── alembic/                    # Database migrations
│   ├── env.py                 # Migration environment config
│   ├── versions/              # Migration scripts
│   └── script.py.mako         # Migration template
├── app/
│   ├── main.py                # FastAPI app initialization
│   ├── core/
│   │   ├── config.py          # Application settings & env variables
│   │   ├── security.py        # JWT & password hashing utilities
│   │   └── exceptions.py      # Custom exception definitions
│   ├── db/
│   │   └── database.py        # SQLAlchemy setup & session management
│   ├── models/                # SQLAlchemy ORM models
│   │   ├── tenants.py         # Tenant (rental business) models
│   │   ├── users.py           # User accounts & authentication
│   │   ├── clients.py         # Client/customer information
│   │   ├── vehicles.py        # Vehicle fleet management
│   │   ├── bookings.py        # Booking & rental agreements
│   │   ├── contracts.py       # Contract details & terms
│   │   ├── payments.py        # Payment records & methods
│   │   ├── invoices.py        # Invoice generation & tracking
│   │   ├── subscriptions.py   # Subscription plans & usage
│   │   └── tenant_policies.py # Tenant-specific business rules
│   ├── schemas/               # Pydantic request/response models
│   │   └── [corresponding schemas for each model]
│   ├── routers/               # API endpoints
│   │   ├── auth.py            # Authentication & authorization
│   │   ├── admin.py           # Admin operations
│   │   ├── tenants.py         # Tenant management
│   │   ├── users.py           # User management
│   │   ├── clients.py         # Client management
│   │   ├── vehicles.py        # Vehicle management
│   │   ├── bookings.py        # Booking operations
│   │   ├── contracts.py       # Contract management
│   │   ├── payments.py        # Payment tracking
│   │   ├── invoices.py        # Invoice management
│   │   ├── subscriptions.py   # Subscription management
│   │   ├── reports.py         # Analytics & reporting
│   │   └── tenant_policies.py # Policy management
│   ├── dependencies/          # Dependency injection
│   │   ├── auth.py            # Authentication dependencies
│   │   ├── rbac.py            # Authorization dependencies
│   │   └── subscription.py    # Subscription helpers
│   ├── services/              # Business logic layer
│   │   ├── contracts.py       # Contract generation logic
│   │   ├── email.py           # Email sending service
│   │   ├── pdf.py             # PDF generation service
│   │   └── reports.py         # Report generation logic
│   └── jobs/                  # Background job processing
│       ├── scheduler.py       # APScheduler setup
│       ├── booking_jobs.py    # Booking-related async tasks
│       └── subscription_jobs.py # Subscription billing tasks
├── scripts/                   # Utility scripts
│   ├── seed_superadmin.py    # Initialize superadmin user
│   ├── seed_tenant_admins.py # Create sample tenant admins
│   └── seed_tenant_policies.py # Initialize default policies
├── storage/
│   └── contracts/             # Generated contract PDF storage
├── requirements.txt           # Python dependencies
└── alembic.ini               # Alembic configuration

```

## 📋 Prerequisites

- **Python 3.8+** (tested with 3.9+)
- **PostgreSQL 12+** (database server)
- **pip** or **poetry** (Python package manager)
- **Git** (for version control)

## 🚀 Installation & Setup

### 1. Clone the Repository

```bash
git clone <repository-url>
cd rental-manager-backend
```

### 2. Create Virtual Environment

```bash
# Using venv
python -m venv venv

# Activate virtual environment
# On Linux/Mac:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Create PostgreSQL Database

```bash
# Connect to PostgreSQL
psql -U postgres

# Create database
CREATE DATABASE rental_manager;
CREATE USER rental_user WITH PASSWORD 'secure_password';
ALTER ROLE rental_user SET client_encoding TO 'utf8';
ALTER ROLE rental_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE rental_user SET default_transaction_deferrable TO on;
GRANT ALL PRIVILEGES ON DATABASE rental_manager TO rental_user;
```

### 5. Configure Environment Variables

Create a `.env` file in the project root:

```bash
# Copy from template (if exists) or create manually
cp .env.example .env
```

## 🔧 Environment Configuration

Create a `.env` file with the following variables:

```env
# Application
APP_NAME="Rental Manager API"
ENVIRONMENT="development"
DEBUG=True
SECRET_KEY="your-secret-key-generate-with-openssl-rand-hex-32"

# Database
DATABASE_URL="postgresql://rental_user:secure_password@localhost:5432/rental_manager"

# Authentication
ACCESS_TOKEN_EXPIRE_MINUTES=60
SUPERADMIN_PASSWORD="initial-superadmin-password"
TENANT_ADMIN_PASSWORD="initial-tenant-admin-password"

# CORS
CORS_ORIGINS=["http://localhost:3000", "http://localhost:5173", "http://localhost:3002"]
FRONTEND_URL="http://localhost:3002"

# Email (Resend API)
RESEND_API_KEY="your-resend-api-key"
FROM_EMAIL="noreply@yourdomain.com"
FROM_NAME="Rental Manager"
```

**Generating a SECRET_KEY:**

```bash
# On Linux/Mac
openssl rand -hex 32

# Or using Python
python -c "import secrets; print(secrets.token_hex(32))"
```

## 🗄️ Database Migrations

### Run Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Create new migration (after modifying models)
alembic revision --autogenerate -m "Description of changes"

# View migration history
alembic history

# Rollback to previous migration
alembic downgrade -1
```

### Initialize Database with Seed Data

```bash
# Create superadmin user
python -m app.scripts.seed_superadmin

# Create sample tenant admins (optional)
python -m app.scripts.seed_tenant_admins

# Create default tenant policies
python -m app.scripts.seed_tenant_policies
```

## ▶️ Running the Application

### Development Server

```bash
# Start with auto-reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Or with more verbose logging
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --log-level debug
```

### Production Server

```bash
# Using gunicorn (recommended for production)
pip install gunicorn

gunicorn app.main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Check Health

```bash
curl http://localhost:8000/health
```

## 📚 API Documentation

Once the server is running, visit:

- **Interactive API Docs (Swagger UI)**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Alternative API Docs (ReDoc)**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

### API Endpoints Overview

| Module | Endpoints |
|--------|-----------|
| **Auth** | `POST /api/auth/login`, `POST /api/auth/refresh`, `POST /api/auth/logout` |
| **Users** | `GET/POST /api/users`, `GET/PUT /api/users/{id}`, `DELETE /api/users/{id}` |
| **Tenants** | `GET/POST /api/tenants`, `GET/PUT /api/tenants/{id}` |
| **Clients** | `GET/POST /api/clients`, `GET/PUT /api/clients/{id}`, `DELETE /api/clients/{id}` |
| **Vehicles** | `GET/POST /api/vehicles`, `GET/PUT /api/vehicles/{id}`, `DELETE /api/vehicles/{id}` |
| **Bookings** | `GET/POST /api/bookings`, `GET/PUT /api/bookings/{id}`, `POST /api/bookings/{id}/cancel` |
| **Contracts** | `GET/POST /api/contracts`, `GET /api/contracts/{id}/pdf` |
| **Payments** | `GET/POST /api/payments`, `GET/PUT /api/payments/{id}` |
| **Invoices** | `GET/POST /api/invoices`, `GET /api/invoices/{id}/pdf` |
| **Subscriptions** | `GET/POST /api/subscriptions`, `PUT /api/subscriptions/{id}` |
| **Reports** | `GET /api/reports/revenue`, `GET /api/reports/utilization` |

## 🔐 Authentication & Authorization

### JWT Authentication Flow

1. **Login**: `POST /api/auth/login` with credentials
   ```json
   {
     "email": "user@example.com",
     "password": "password"
   }
   ```

2. **Receive Tokens**: Response contains `access_token` and `refresh_token`
   ```json
   {
     "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
     "refresh_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
     "token_type": "bearer"
   }
   ```

3. **Use Access Token**: Include in all API requests
   ```
   Authorization: Bearer <access_token>
   ```

4. **Refresh Token**: Get new access token before expiry
   ```
   POST /api/auth/refresh
   ```

### Role-Based Access Control (RBAC)

Available roles:
- **SUPERADMIN** - Full system access, manage all tenants
- **TENANT_ADMIN** - Manage own tenant, users, and business operations
- **TENANT_USER** - Limited access to tenant resources
- **CLIENT** - Read-only access to own bookings and contracts

Permissions are enforced at the endpoint level using dependency injection in `app/dependencies/rbac.py`.

## 🎯 Project Features

### 1. Multi-Tenant Architecture
- Isolated data per rental business
- Shared infrastructure for cost efficiency
- Tenant-specific policies and configurations

### 2. Booking Management
- Create rental agreements with date/time validation
- Automatic booking status tracking
- Integration with vehicle availability

### 3. Contract Generation
- PDF contracts generated automatically
- Customizable terms and conditions
- Legal compliance documentation

### 4. Payment Processing
- Multiple payment method support
- Payment tracking and reconciliation
- Partial payment handling

### 5. Subscription Management
- Flexible subscription tier system
- Usage tracking and billing
- Automated renewal notifications

### 6. Reporting & Analytics
- Revenue reports by period
- Vehicle utilization metrics
- Client activity summaries

## ⏰ Background Jobs

Scheduled jobs are managed by APScheduler:

### Subscription Jobs (`subscription_jobs.py`)
- Renewal reminders
- Automatic billing
- Subscription expiration handling

### Booking Jobs (`booking_jobs.py`)
- Booking reminders
- Overdue vehicle alerts
- Return notifications

Jobs start automatically when the application starts and stop gracefully on shutdown.

## 🤝 Contributing

### Development Workflow

1. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make changes** and test thoroughly:
   ```bash
   # Run migrations if needed
   alembic upgrade head
   
   # Test your changes
   # ...
   ```

3. **Commit with clear messages**:
   ```bash
   git commit -m "feat: add new feature description"
   ```

4. **Push and create a pull request**:
   ```bash
   git push origin feature/your-feature-name
   ```

### Code Standards
- Follow PEP 8 style guidelines
- Add type hints to functions
- Document complex business logic
- Write descriptive commit messages
- Test all new features

### Database Changes
- Always use Alembic migrations: `alembic revision --autogenerate -m "description"`
- Never modify the database directly
- Test migrations on a copy of production data

## 🐛 Troubleshooting

### Common Issues

**Issue**: Database connection refused
```
Solution: Check PostgreSQL is running and DATABASE_URL is correct in .env
```

**Issue**: Migrations fail
```
Solution: Ensure database exists, run: psql -c "DROP DATABASE IF EXISTS rental_manager; CREATE DATABASE rental_manager;"
Then run: alembic upgrade head
```

**Issue**: JWT token errors
```
Solution: Verify SECRET_KEY is set correctly in .env and hasn't changed
```

**Issue**: CORS errors from frontend
```
Solution: Add frontend URL to CORS_ORIGINS in .env file
```

## 📞 Support & Contact

For issues, questions, or contributions, please reach out or create an issue in the repository.

---

**Last Updated**: June 2026
**Maintained By**: Development Team
