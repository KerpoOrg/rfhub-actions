# rfhub-actions

GitHub Actions for [Robot Framework Hub](https://rfhub.kerpo.org).

All actions talk to production Hub. The commit is the PR head SHA on
`pull_request`, otherwise `github.sha`. Python 3 is required on the runner.

## Check / Run (suite or test UUID)

Succeeds if this suite or test UUID already has a passing Hub run for the
current commit (`check`), or queues that UUID and waits (`run`).

```yaml
- uses: KerpoOrg/rfhub-actions/check@main
  id: hub
  continue-on-error: true
  with:
    id: df054561-8087-48a3-b4e0-ff1af1651900
    token: ${{ secrets.RFHUB_TOKEN }}
- uses: KerpoOrg/rfhub-actions/run@main
  if: steps.hub.outcome == 'failure'
  with:
    id: df054561-8087-48a3-b4e0-ff1af1651900
    token: ${{ secrets.RFHUB_TOKEN }}
```

## Acceptance check / run (definition slug)

Prefer these for PR image gates. They look for a **ready + passed** acceptance
report with `definitionSlug` matching the slug (default `pr`) — not “any green
run”.

```yaml
- uses: KerpoOrg/rfhub-actions/acceptance-check@main
  id: gate
  continue-on-error: true
  with:
    project: 11111111-0000-4000-8000-000000000100
    acceptance: pr
    token: ${{ secrets.RFHUB_TOKEN }}
- uses: KerpoOrg/rfhub-actions/acceptance-run@main
  if: steps.gate.outcome == 'failure'
  with:
    project: 11111111-0000-4000-8000-000000000100
    acceptance: pr
    environment: dev
    token: ${{ secrets.RFHUB_TOKEN }}
```

Create the acceptance definition once in Hub (Settings → Acceptance), e.g. slug
`pr` with wave `analysis`.
