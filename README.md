# Desktop Upgrade State Gate

Electron and other Windows desktop applications can launch successfully after an upgrade while silently
changing, orphaning or dropping persisted user state. Desktop Upgrade State
Gate turns one old-version-to-candidate migration path into a blocking Windows
CI check with retained evidence.

The action does not guess whether two folders look similar. A project-owned
adapter:

1. launches or drives a pinned shipped build with synthetic data;
2. preserves its isolated profile;
3. launches or drives the candidate against that profile;
4. emits a small JSON witness of the state semantics that matter; and
5. fails closed when the witness, process result or assertion is wrong.

The reusable engine is free. The commercial hypothesis starts with a fixed-scope
founding integration pilot for teams that want their first real migration path
implemented without building the adapter themselves. A sustainable business
would additionally require teams to pay for recurring adapter maintenance,
release evidence and failure triage. Neither payment nor renewal is validated.

## Minimal workflow

This unreleased example shows the intended interface. Replace the placeholder
tag with a published immutable release tag only after one exists.

```yaml
name: Desktop migration gate

on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  old-to-candidate:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6

      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6
        with:
          python-version: '3.13'

      - name: Build candidate
        shell: pwsh
        run: ./scripts/build.ps1

      - name: Prove retained state semantics
        id: state_gate
        uses: pupajasia/state-migration-gate-historical-proof@RELEASE_TAG
        with:
          config: state-gate.json
          previous-repo: your-org/your-desktop-app
          previous-release: v1.8.4
          previous-asset-name: your-app-portable.exe
          previous-sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
          candidate-artifact: dist/your-app-portable.exe

      - name: Retain migration evidence
        if: always()
        uses: actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02 # v4
        with:
          name: state-migration-evidence
          path: .state-gate-results
```

The previous artifact can instead be a repository file supplied through
`previous-artifact`. Exactly one previous source is required. The previous
artifact always needs an exact SHA-256 pin; `latest`, ambiguous asset selection,
workspace escapes and non-Windows runners are rejected before execution. A
candidate pin is optional, but its computed digest is always exposed as an
action output.

## State contract

`state-gate.json` is a versioned, strict JSON contract. Each path has a seed
command, a verify command and assertions over the verify command's JSON
evidence. Commands are argument arrays and are never passed through a shell.

```json
{
  "$schema": "./state-gate.schema.json",
  "contract_version": 1,
  "project": "your-desktop-app",
  "fail_on_flaky": true,
  "paths": [
    {
      "id": "v1.8.4-to-candidate",
      "from": "v1.8.4",
      "to": "candidate",
      "timeout_seconds": 180,
      "retries": 0,
      "seed": {
        "command": [
          "node", "test/migration-adapter.mjs", "seed",
          "{previous_artifact}", "{profile}", "{evidence}"
        ]
      },
      "verify": {
        "command": [
          "node", "test/migration-adapter.mjs", "verify",
          "{candidate_artifact}", "{profile}", "{evidence}"
        ]
      },
      "assertions": [
        { "path": "passed", "op": "equals", "value": true },
        { "path": "workspace.stable_id", "op": "equals", "value": "workspace-42" }
      ]
    }
  ]
}
```

The adapter is deliberately project-owned: only the application team knows
which IDs, relations, restored views, migration markers and database meanings
constitute correct retained state. The action owns the repeatable runner,
isolation, fail-closed verdict, hashes, logs and report format.

See `fixtures/action-smoke/` for a deterministic pass/block example and
`adapters/beekeeper/` for a real Electron/SQLite historical proof adapter.

## Historical proof

The first public proof downloads hash-pinned Beekeeper Studio portable releases
`v5.8.1` and `v5.9.0` on a disposable Windows runner. It establishes both sides
of the claim:

| Transition | Required result |
|---|---|
| `v5.8.1` to `v5.8.1` | **BLOCK**: reproduce the historical retained-edit loss |
| `v5.8.1` to `v5.9.0` | **PASS**: preserve the retained edit and database semantics |

The [public passing run](https://github.com/pupajasia/state-migration-gate-historical-proof/actions/runs/33874104060)
retained reports, logs, JSON witnesses and screenshots. Its downloaded evidence
artifact was independently checked as SHA-256
`f394f50e54bb3a60ad94036cff43a321a9b30c2b2fae4740d5b4f81dff867e84`.

This is an independent technical experiment and is not affiliated with or
endorsed by Beekeeper Studio.

## Safety boundary

- Windows runner only; disposable GitHub-hosted runners are recommended.
- Synthetic test data and isolated profiles only.
- Previous releases use an explicit tag, one exact asset and a verified digest.
- Read-only repository permission is sufficient for public release artifacts.
- Commands run without a shell; failures, timeouts and malformed evidence block.
- No telemetry, hosted service or upload is implemented by this action.
- Do not place production credentials or customer data in an adapter or report.

Review the adapter like other test code before running it. Third-party binaries
still execute on the selected runner, so use artifacts you are legally and
operationally entitled to test.

## Voluntary pilot interest

Teams may voluntarily open the **Founding pilot interest** issue form with only
non-confidential details. This is a request for a scoped discussion, not an
order. The current test offer is one Windows old-to-candidate path for EUR 149
net, subject to written scope, business/tax readiness and acceptance before any
payment. No unsolicited sales email is part of the launch plan.

## Current maturity

The engine and historical proof work. The composite Marketplace package is a
local release candidate until its Windows workflow passes from a pushed tag and
the repository owner completes the publication checklist. It should not yet be
described as a generally available or commercially validated product.
