### Changed

- `fleet-verify.yml`: a repo whose `app:` block gives nothing to start or serve on a local URL now stops in seconds with a **Not verified** warning and job summary, and fails under `gate: true`. An app that is configured but fails to build or start now fails the job whatever `gate` says, because no scenario ran. Until now both cases waited out the readiness timeout and passed.
