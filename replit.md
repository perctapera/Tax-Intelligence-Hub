# TMCIS Intelligence

A fictional-data, role-based prototype for merchant tax-compliance workflows and human-reviewed investigations.

## Run & Operate

- API workflow: `uv run --project . python backend/manage.py runserver 0.0.0.0:8080`
- Web workflow: `pnpm --filter @workspace/tmcis-intelligence run dev`
- Initialize demo DB: `uv run --project . python backend/manage.py migrate`
- Seed demo records: `uv run --project . python backend/manage.py seed_tmcis_demo`
- Backend tests: `uv run --project . python backend/manage.py test tmcis`
- Frontend typecheck/build: `pnpm --filter @workspace/tmcis-intelligence run typecheck` / `PORT=21876 BASE_PATH=/ pnpm --filter @workspace/tmcis-intelligence run build`
- SQLite is the default. Set `DATABASE_URL` for PostgreSQL; keep credentials in Replit Secrets.

## Stack

- Backend: Python 3.12, Django 5.2, Django REST Framework
- Frontend: Vue 3, Vite, Vue Router, Pinia, TypeScript
- Database: SQLite for local demo; PostgreSQL supported through `DATABASE_URL`
- Authentication: Django session cookies with CSRF protection

## Where things live

- `backend/tmcis/` — domain models, API, serializers, permissions, services, tests, and seed command
- `backend/tmcis_backend/` — Django settings and root URL configuration
- `artifacts/tmcis-intelligence/src/` — Vue application, route views, API client, and styles
- `artifacts/api-server/.replit-artifact/artifact.toml` — managed Django API workflow
- `README.md` — demo setup, scope limits, checks, and production cautions

## Architecture decisions

- External financial and TaRMS integrations are intentionally simulated or CSV-based.
- Social intelligence is limited to authorized public business information entered manually or from CSV.
- Risk assessment is an explainable staff review aid; it does not make enforcement decisions.
- Role and object-level access rules are enforced by the API, not just by the frontend.

## Product

Role-based dashboards and workflows cover merchant profiles and declarations, financial-source imports and reconciliation, identity candidates, investigations, public social leads, audit records, CSV exports, and simulated TaRMS verification and transfers.

## User preferences

The supplied build brief requires Django 5.2 + DRF and Vue 3 + Vite, fictional demo data, explicit human review, and no claims of live integrations.

## Gotchas

_Populate as you build — sharp edges, "always run X before Y" rules._

## Pointers

- `README.md` is the developer setup and scope guide.
