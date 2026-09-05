# Security Policy

## Supported versions

The first technical public-beta line is `0.1.x`. Fixes are prepared against the
latest supported release and the default branch.

| Version | Supported |
|---|---|
| 0.1.x | Best effort |
| Earlier or unlisted versions | No |

## Report a vulnerability privately

Do not open a public issue for a suspected vulnerability.

Use this repository's **Security → Advisories → Report a vulnerability** flow.
GitHub private vulnerability reporting is enabled for this repository.

Please include, where relevant:

- the affected commit, tag or immutable action reference;
- operating system and runner type;
- a minimal reproduction using synthetic data;
- the security impact and the trust boundary that was crossed;
- hashes for involved artifacts;
- whether logs or evidence may contain secrets.

Do not include real credentials, production customer data or personal data in
the initial report. We may ask for a safer minimized reproduction.

## Response targets

This project has no 24/7 security operation. We aim to:

- acknowledge a complete private report within three business days;
- provide an initial triage decision within seven business days;
- keep the reporter informed when remediation timing changes.

These are targets, not a service-level agreement. If a report is accepted, use
the private advisory for coordinated discussion until a fix and disclosure plan
are agreed.

## Security-relevant scope

Examples that belong in a private report include:

- workspace or output-path escape;
- authentication-token or secret disclosure, including across redirects;
- command or argument injection through action inputs or the JSON contract;
- previous/candidate artifact substitution or digest-verification bypass;
- evidence or verdict tampering that can turn a failed gate into PASS;
- execution outside the documented Windows runner or profile isolation
  boundary.

The following are usually not vulnerabilities in this repository:

- a migration defect in the third-party desktop application being tested;
- an expected BLOCK or evidence-error verdict;
- GitHub, runner-image or upstream dependency availability;
- requests for general product support or analysis of real customer data.

## Safe-harbor boundary

No vulnerability bounty is offered. Research must use accounts and systems you
own or are explicitly authorized to test, avoid privacy violations and service
degradation, and stop after obtaining the minimum evidence necessary to report
the issue. This policy does not authorize testing third-party applications,
repositories, accounts or infrastructure.
