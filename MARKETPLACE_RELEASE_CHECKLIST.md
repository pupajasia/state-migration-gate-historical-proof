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
- [ ] GitHub parses the metadata and the Windows package workflow passes on the
      exact commit intended for release.
- [ ] Repository owner selects and adds an explicit software license.

## Public-state gates — owner approval required

- [ ] Approve pushing the release-candidate branch.
- [ ] Review all public wording, the EUR 149 test offer and the voluntary issue
      form.
- [ ] Enable GitHub private vulnerability reporting or nominate a private
      security contact before inviting broad use.
- [ ] Confirm the Marketplace name remains available immediately before release.
- [ ] Select `Testing` and `Continuous integration` as Marketplace categories if
      both are available at release time.
- [ ] Approve and create an immutable `v1.0.0` tag/release.
- [ ] Accept the current GitHub Marketplace terms and publish the action.
- [ ] Approve any LinkedIn Service Page or Product Hunt launch separately.

## Commercial gates — before accepting an order or payment

- [ ] Confirm who provides the service and which legal name/address appears on
      scope confirmation and invoice.
- [ ] Confirm German business-registration and tax treatment with the relevant
      authority or qualified adviser.
- [ ] Confirm invoice wording, VAT treatment and a permitted SEPA account.
- [ ] Keep the first offer to at most three EUR 149-net founding pilots.
- [ ] Record opt-in source, scope, price acceptance, payment and acceptance result.

The project is not commercially validated until two independent teams have paid
for pilots. Marketplace runs, stars, issue reactions and compliments are useful
signals but do not satisfy that gate.
