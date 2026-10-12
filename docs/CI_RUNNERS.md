# CI runner images

Majd sales tests and the inherited Python/Botpress test jobs use explicit
`ubuntu-26.04` runners, with Python 3.12 and Node.js 22. The existing live
verification job remains pinned to `ubuntu-24.04` until its Ubuntu 26.04
behavior is separately validated. No workflow relies on `ubuntu-latest`.

Before this deliberate test-runner migration, Ubuntu 26.04 compatibility run
[37690880873](https://github.com/alikartemir1988-gif/customer-agent-v62/actions/runs/37690880873)
passed on Ubuntu 26.04.1 LTS with Python 3.12.14 and Node 22.23.3: compilation,
three Gunicorn entry-point checks, all 87 Python tests (including Majd sales
and mocked live-verifier regressions), Botpress typecheck, and production
dependency audit (0 vulnerabilities). The older brace-expansion 5.0.9 lock
entry was updated to the patched 5.0.12 already used on main before testing.

`ubuntu-26-compatibility.yml` continues to test the current checkout on
`ubuntu-26.04`, verifies the actual Ubuntu release, and runs the same Python
and Botpress checks. The corresponding workflow on `main` checks that
branch's current V6 application and Botpress adapter.

Both compatibility workflows have read-only repository permissions and do
not use production credentials, deploy services, register webhooks, or invoke
the live verification script against a service. The portable container job
on `main` likewise remains on Ubuntu 24.04.

Rollback consists of restoring the migrated jobs' `runs-on` values to
`ubuntu-24.04`. GitHub's automatic alias migration between October 19 and
November 19, 2026 will not change the explicitly selected runners.

Reference: [GitHub's Ubuntu 26 migration announcement](https://github.blog/changelog/2026-09-17-ubuntu-26-generally-available-and-latest-migration/).
