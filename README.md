# TMCIS Intelligence

A role-based prototype for Zimbabwe tax-compliance review. It supports fictional merchant declarations, transaction imports, reconciliation, explainable risk indicators, investigations, public-business social leads, audit events, and a simulated TaRMS adapter.

## Prototype boundaries

- All seeded merchants, transactions, taxpayer-directory records, and social leads are fictional.
- Bank and mobile-money feeds are not connected. Staff can import CSVs with source and file provenance.
- Social leads are entered manually or imported from CSV; the prototype does not scrape sites or access private communications.
- TaRMS checks, links, and transfers use a local simulated adapter. No external service is contacted.
- Risk scores are explainable review aids, not proof of wrongdoing or automated enforcement decisions. Staff decisions remain human-reviewed.
- The example TIN rule (`200076899X`) is prototype validation only, not official Zimbabwe Revenue Authority validation. The fixed pattern has ten valid fixtures; invalid seeded merchant profiles are clearly marked review examples.

## Start the demo

The Replit workspace starts the Vue web app and Django API as separate services. To initialize the local database:

```bash
uv run --project . python backend/manage.py migrate
uv run --project . python backend/manage.py seed_tmcis_demo
```

The repeatable seed command creates fictional staff and merchant accounts and prints the shared development-only password. Never reuse those accounts or that password in a real environment.

Local setup outside the managed Replit workflows:

```bash
uv sync --project .
uv run --project . python backend/manage.py migrate
uv run --project . python backend/manage.py seed_tmcis_demo
uv run --project . python backend/manage.py runserver 0.0.0.0:8080
```

In a second terminal:

```bash
PORT=21876 BASE_PATH=/ pnpm --filter @workspace/tmcis-intelligence run dev
```

## Demo accounts

After seeding, use one of these fictional roles:

- `admin_demo` — administrator
- `supervisor_demo` — supervisor
- `officer_demo1` — compliance officer
- `merchant_demo1` — merchant

The seed command prints the demo password in the terminal. The command refuses to run with Django debug mode disabled.

## Database

SQLite is used when `DATABASE_URL` is empty. To use PostgreSQL, set `DATABASE_URL` to a PostgreSQL connection string using Replit Secrets or a local, untracked environment file, then run migrations. Do not place real credentials in source control.

## Checks

```bash
uv run --project . python backend/manage.py check
uv run --project . python backend/manage.py test tmcis
pnpm --filter @workspace/tmcis-intelligence run typecheck
PORT=21876 BASE_PATH=/ pnpm --filter @workspace/tmcis-intelligence run build
```

## API

The Django API is served through the existing `/api` service path. Versioned application endpoints are under `/api/api/v1/` in the Replit preview; for example, `/api/api/v1/healthz`. Session authentication and CSRF protection are used by the web client.

## Production warning

This is a functional demonstration, not an approved production compliance platform. Before any real use, configure authorized data sources and official TIN validation, review data-protection and retention rules, threat-model and penetration-test the application, establish operational controls and incident response, and validate all legal and regulatory requirements.
