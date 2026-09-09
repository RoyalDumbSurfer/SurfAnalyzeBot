# RU/EN foundation

Russian is the default for browsers without a valid language preference. The header's RU / EN form changes a year-long HttpOnly, SameSite=Lax cookie (`surfanalyze_language`), Secure when `SESSION_COOKIE_SECURE=true`. Login/logout do not reset this preference. It is a browser preference, not an account setting; devices choose independently.

`webapp/i18n.py` provides request-local `t(message, **values)` to existing templates. English source strings are catalog keys; Russian translations live in `webapp/locales/ru.json`. Missing entries fall back to English. Add a language catalog and its supported language entry to extend this layer. User-generated filenames and saved coaching are never translated as template strings. JavaScript translations use Jinja's `tojson`, and ordinary HTML remains escaped. Internal logs and API error identifiers remain English.

The POST `/language` endpoint validates CSRF and Origin, bounds the request body, accepts only supported languages, and redirects only to known local pages. It is available before login but exposes no user resources.

New uploads save `analysis_language` inside the existing SQLite job payload. No SQL schema migration is needed. The worker passes the saved language to the provider, which requests Russian/English values while preserving all six JSON field names and the existing schema. Sampling is unchanged. Existing jobs and already-generated analysis remain in their original language; switching the interface does not rerun paid analysis.

Deployment of accounts follows [the migration runbook](accounts-migration-runbook.md). No new environment variables are needed for localization. Keep the existing OpenAI configuration, 50 MiB application limit, and secure session settings.

Validation includes RU/EN pages and rendered JavaScript syntax, preference persistence across login/logout, CSRF/Origin/redirect checks, saved job language, real frame extraction with provider mocked, and provider schema/language assertions. Production acceptance additionally requires real HTTPS login and upload through the running worker/OpenAI service.
