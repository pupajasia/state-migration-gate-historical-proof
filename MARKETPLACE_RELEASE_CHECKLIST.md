# Marketplace release checklist

This checklist separates local engineering completion from actions that change
public state or create legal/commercial commitments.

## Local engineering gates

- [x] One root `action.yml` with Marketplace name, description and branding.
- [x] Exactly one pinned previous-artifact source is enforced.
- [x] Candidate and report paths are contained in `GITHUB_WORKSPACE`.
- [x] Passing semantic fixture exits 0.
- [x] Silently changed semantic fixture exits 1 and retains the witness.
- [x] Standard-library unit tests cover action preflight and executable evidence.
- [x] Python and Node sources pass syntax checks.
- [x] A Windows workflow exercises the action through `uses: ./`.
- [ ] GitHub parses the metadata and the corrected Windows package workflow,
      including hidden evidence retention, passes on the exact commit intended
      for release. The latest public package smoke passed at `fc99938`; the
      final release commit and tag still need their own green runs.
- [x] Repository owner selected MIT and added exact licensor `Kevin Kober`.
- [x] GitHub private vulnerability reporting is enabled and `SECURITY.md` points
      reporters to that private channel without publishing a personal address.
- [x] Add and maintain a third-party notice for referenced dependencies and test
      targets; do not bundle third-party application binaries, source, icons or
      plugins.
- [ ] Use only owned/synthetic launch media unless third-party UI and trademark
      use has a documented permission or legal basis.

## Public-state gates — owner approval required

- [x] Owner authorized the remaining staged technical publication steps, but no
      email, direct-message or paid-account action.
- [ ] Review all public wording, the EUR 149 price hypothesis and voluntary issue
      form.
- [x] Enable GitHub private vulnerability reporting before publishing the
      security policy.
- [ ] Confirm the Marketplace name remains available immediately before release.
- [ ] Select `Testing` and `Continuous integration` as Marketplace categories if
      both are available at release time.
- [ ] Create and verify the first immutable `v0.1.0` tag/release.
- [ ] Accept the current GitHub Marketplace terms and publish the action.
- [ ] Approve any LinkedIn Service Page or Product Hunt launch separately.
- [ ] Approve any Upwork profile, Project Catalog listing, proposal or Connect
      spend separately.

## Commercial gates — before accepting an order or payment

- [ ] Confirm who provides the service and which legal name/address appears on
      scope confirmation and invoice.
- [ ] Confirm German business-registration and tax treatment with the relevant
      authority or qualified adviser.
- [ ] Publish a compliant provider notice with legal name, service address and
      business email before accepting payment or adding a checkout.
- [ ] Confirm invoice wording, VAT treatment and a permitted SEPA account.
- [ ] Keep the first offer to at most three EUR 149 price-test founding pilots;
      confirm the final invoice total and tax treatment before acceptance.
- [ ] Record opt-in source, scope, price acceptance, payment and acceptance result.

The project is not commercially validated until two independent teams have paid
for pilots. Marketplace runs, stars, issue reactions and compliments are useful
signals but do not satisfy that gate.
