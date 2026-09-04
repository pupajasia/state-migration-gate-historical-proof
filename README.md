# State Migration Gate: Beekeeper historical proof

This temporary proof repository tests one narrow release risk: whether retained
desktop state survives an application upgrade with the same meaning and
relationships, not merely whether the new executable launches.

The manually dispatched Windows workflow downloads the public, hash-pinned
Beekeeper Studio portable releases `v5.8.1` and `v5.9.0`, then runs two isolated
transitions with synthetic local data:

| Transition | Expected gate result |
|---|---|
| `v5.8.1` to `v5.8.1` | **BLOCK**: historical control reproduces the lost retained edit |
| `v5.8.1` to `v5.9.0` | **PASS**: the fix preserves the retained edit and database semantics |

The gate creates a harmless local SQLite connection and query through the old
UI. It records stable IDs, relations, SQL meanings, migration names and SQLite
integrity, launches the candidate against the retained portable profile, and
requires both UI restoration and database semantics to match. A failed or
incomplete check blocks by default.

## Safety boundary

- GitHub-hosted disposable Windows runner only
- synthetic data and local loopback debugging only
- public release downloads verified by exact SHA-256
- read-only repository permission and no repository secrets
- update checks disabled for the tested application
- receipts, logs, JSON witnesses and screenshots retained as a workflow artifact

No Beekeeper binary is committed to this repository. This is an independent
technical experiment and is not affiliated with or endorsed by Beekeeper
Studio.

## Run

Open **Actions**, select **Beekeeper historical state-gate proof**, and dispatch
the workflow. The expected red control is handled as a successful assertion;
the job succeeds only if the control blocks and the fixed transition passes.
