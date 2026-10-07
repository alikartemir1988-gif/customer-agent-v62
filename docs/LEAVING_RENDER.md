# V6 hosting migration

## Verified on 7 October 2026

Production V6 uses the existing Supabase project `customer-agent-v6`
(`hojrymxbbpkxhviuykwy`). Its nine tables are protected by RLS and have no
`anon` or `authenticated` table access. The old Render database is a legacy
copy; it expires on 8 October at 12:57:59 UTC. That expiry is separate from
Render's free web-service lifecycle.

The production `/ready` endpoint returned HTTP 200, version 6.5.4,
`database: ok` and `configuration: ok`. A Supabase session read/write probe
passed in a rolled-back transaction. The existing order and all 96 legacy
Telegram update IDs remain in Supabase, which now has 109 update IDs.
The backup is kept privately outside this public repository.

## Native Supabase component

`v6-storage-readiness` is a read-only Edge Function deployed to the existing
project with JWT verification enabled. It uses the built-in database connection
to run a zero-row SQL probe. It returns only storage
status, never orders, messages, credentials or upstream errors. It does not
call Render and does not implement the sales bot.

Supabase runs TypeScript/Deno Edge Functions; the Python/Flask core, dashboard
and HTML demo need a port before they can run there. Default Edge Function
domains rewrite HTML responses to plain text. A free, complete Supabase
cutover has not happened. The Edge Function is the first isolated component.

## Portable Python runtime

The Docker image can run the existing core, demo or dashboard on a container
host. It runs as an unprivileged user, excludes local secrets and databases,
accepts `PORT`, preserves deployed commit metadata, and supplies a health
probe. Core and dashboard require `DATABASE_URL`; demo uses one worker and
keeps its conversations in memory without database access.

Build from the exact reviewed commit:

```sh
docker build --build-arg APP_GIT_COMMIT="$(git rev-parse HEAD)" -t customer-agent-v6 .
```

Create a private environment file on the selected host from the existing
production settings. Copy the Supabase connection settings, including
`PGPASSWORD` when the connection URL omits the password. Keep `sslmode=require`
for the hosted connection. Do not place credentials in Git, build arguments
or screenshots. Set `APP_GIT_COMMIT` to the deployed commit if the environment
file overrides the value baked into the image.

The production settings needed by core include `TELEGRAM_BOT_TOKEN`,
`WEBHOOK_URL`, `TELEGRAM_WEBHOOK_SECRET`, `ADMIN_API_KEY`, and
`DASHBOARD_SESSION_SECRET`, plus merchant configuration and any existing
Gemini/Langfuse/Meta/Botpress integration credentials. A staging instance
must not receive production webhook traffic.

```sh
docker run --env-file /private/v6-staging.env \
  -e APP_SERVICE=core -e TELEGRAM_REGISTER_WEBHOOK_ON_START=false \
  -p 8080:8080 customer-agent-v6
docker run --env-file /private/v6-demo.env \
  -e APP_SERVICE=demo -e DEMO_COOKIE_SECURE=true \
  -p 8081:8080 customer-agent-v6
docker run --env-file /private/v6-staging.env \
  -e APP_SERVICE=dashboard -p 8082:8080 customer-agent-v6
```

Place the services behind HTTPS. Give demo a stable, independent
`DEMO_SESSION_SECRET` so cookies survive restarts. The existing Majd service
is on a separate branch and is not included in this image or moved by this PR.

## Cutover and rollback

1. Deploy a staged instance on the chosen free host and keep
   `TELEGRAM_REGISTER_WEBHOOK_ON_START=false`. Configure its public HTTPS URL.
2. Verify `/ready`, administrative authentication, demo chat/reset, and database
   connectivity. Use synthetic conversations; do not create real orders as a
   readiness check.
3. Before activating the new Telegram endpoint, disable webhook registration
   on the old host. Otherwise a later Render restart can reclaim the webhook.
4. Set the new core's `WEBHOOK_URL` and enable
   `TELEGRAM_REGISTER_WEBHOOK_ON_START=true`. Start it and check `/webhook-info`
   with the expected new URL. Preserve pending updates and the webhook secret.
5. Update the public demo link and any Meta/Botpress callbacks only after their
   independent channel checks. Keep the Render services available for rollback
   until the new live paths pass.
6. To roll back, disable registration on the new host and restore the old
   `WEBHOOK_URL`/registration setting. Continue using Supabase in either case.

No existing Render service, database or bot was deleted or switched by this
preparation. No paid plan was purchased. The free Supabase project can pause
after a week of inactivity; its free-plan limits still apply.

References: [Supabase Functions](https://supabase.com/docs/guides/functions),
[function limits](https://supabase.com/docs/guides/functions/limits),
[free Render resources](https://render.com/docs/free), and
[Supabase plans](https://supabase.com/pricing).
