cd ~/Documents/Projects/rental-manager-backend

# Stage all three files
git add app/models/__init__.py app/models/drivers.py alembic/versions/fe6e52fc6f36_add_drivers_table.py

# Verify
git status --short

# Commit
git commit -m "fix: complete Driver-Booking relationship and ship migration

- Add bookings relationship to Driver model (back_populates='driver')
- Register Driver in app/models/__init__.py before Booking
- Include fe6e52fc6f36 migration file (drivers table)
- Resolves mapper initialization errors on deploy"

# Push
git push origin main
