### Added

- `release-please.yml`: the release is made by a GitHub App. When the caller holds `RELEASE_APP_CLIENT_ID` and `RELEASE_APP_PRIVATE_KEY`, each job mints an installation token for its own repo (contents and pull-requests write, revoked when the job ends) and uses it to tag, to open the release PR and to push the lockfile commit, so the PR runs CI and the tag fires the workflows that listen for it. Nothing expires and one app serves every owner it is installed on. Both secrets are declared under `workflow_call.secrets`, so a caller under another owner can pass them by name. Setup: `docs/RELEASES.md` "The release app".

### Changed

- `release-please.yml`: the credential order is the release app, then `RELEASE_PLEASE_TOKEN`, then `GITHUB_TOKEN`. A caller that holds only the PAT releases exactly as before. The key arms the app: a key without the client ID, or an app that cannot mint a token (not installed on the repo, a key that is not the app's), fails the run and says which, and neither falls back to the PAT. The client ID alone is inert.

### Deprecated

- `release-please.yml`: the `RELEASE_PLEASE_TOKEN` secret. It is still read where the release app is not provisioned, and goes when the fleet's callers no longer hold it.
