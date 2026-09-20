# rfhub-actions

GitHub Actions for [Robot Framework Hub](https://rfhub.kerpo.org).

Both actions talk to production Hub. The commit is the PR head SHA on
`pull_request`, otherwise `github.sha`. Python 3 is required on the runner.

## Check

Succeeds if this suite or test UUID already has a passing Hub run for the
current commit.

```yaml
- uses: KerpoOrg/rfhub-actions/check@main
  with:
    id: df054561-8087-48a3-b4e0-ff1af1651900
    token: ${{ secrets.RFHUB_TOKEN }}
```

## Run

Queues that UUID on Hub and waits for the result. Fails if no orchestrator
can run it, or if the run fails.

```yaml
- uses: KerpoOrg/rfhub-actions/run@main
  with:
    id: df054561-8087-48a3-b4e0-ff1af1651900
    token: ${{ secrets.RFHUB_TOKEN }}
```
