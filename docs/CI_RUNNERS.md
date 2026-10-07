# CI runner images

Python and Botpress tests in `tests.yml` use explicit `ubuntu-26.04` runners,
with Python 3.12 and Node.js 22. The portable container workflow remains pinned
to `ubuntu-24.04` until its Ubuntu 26.04 behavior is separately validated.
No workflow relies on the moving `ubuntu-latest` alias.

Before this deliberate test-runner migration, Ubuntu 26.04 compatibility run
[37690775114](https://github.com/alikartemir1988-gif/customer-agent-v62/actions/runs/37690775114)
passed on Ubuntu 26.04.1 LTS with Python 3.12.14 and Node 22.23.3: compilation,
three Gunicorn entry-point checks, all 132 Python tests, Botpress typecheck,
and production dependency audit (0 vulnerabilities).

`ubuntu-26-compatibility.yml` continues to test the current checkout on
`ubuntu-26.04`. It verifies the actual Ubuntu release, compiles the application
and tests, validates Gunicorn entry points, runs the full Python suite, and
runs the Botpress typecheck and production audit. The corresponding workflow
on `majd-sales-bot` includes that branch's Majd sales and mocked live-verifier
regressions.

Both compatibility workflows have read-only repository permissions and do
not use production credentials, deploy services, register webhooks, or invoke
the live verification script against a service. The existing live-verification
job on `majd-sales-bot` remains pinned to Ubuntu 24.04.

Rollback consists of restoring the migrated jobs' `runs-on` values to
`ubuntu-24.04`. GitHub's automatic alias migration between October 19 and
November 19, 2026 will not change the explicitly selected runners.

Reference: [GitHub's Ubuntu 26 migration announcement](https://github.blog/changelog/2026-09-17-ubuntu-26-generally-available-and-latest-migration/).
