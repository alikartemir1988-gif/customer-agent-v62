# CI runner images

The existing workflows use explicit `ubuntu-24.04` runners. The `ubuntu-latest`
alias is intentionally avoided: GitHub will move it to Ubuntu 26.04 between
October 19 and November 19, 2026.

`ubuntu-26-compatibility.yml` tests the current checkout on `ubuntu-26.04` with
Python 3.12 and Node.js 22. It compiles the Python application, Majd service,
release verifier, and tests; validates Gunicorn entry points; runs the full
Python suite including Majd sales and mocked live-verifier regressions; and
runs the Botpress typecheck and production dependency audit. Each job verifies
the actual Ubuntu release before testing.

The corresponding workflow on `main` checks the current V6 application and
Botpress adapter. Both compatibility workflows have read-only repository
permissions and do not use production credentials, deploy services, register
webhooks, or invoke the live verification script against a service.

After the compatibility runs pass, propose an explicit runner change for the
Python and Botpress tests in a separate PR. Keep the existing live-verification
job on Ubuntu 24.04 until its Ubuntu 26.04 behavior is separately validated.
The portable container job on `main` likewise remains on Ubuntu 24.04.
Rollback consists of restoring the tested jobs' `runs-on` values to
`ubuntu-24.04`.

Reference: [GitHub's Ubuntu 26 migration announcement](https://github.blog/changelog/2026-09-17-ubuntu-26-generally-available-and-latest-migration/).
