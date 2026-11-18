### Fixed

- The fleet-doctor's priority fallback no longer queues a healthy, high-volume workflow. An unflagged workflow now needs its wasted job-minutes, less the minutes its own `cancel-in-progress` superseded, to clear `remediation.min_cost_waste_min` and the new `remediation.fallback_max_waste_pct` share (default 5 %) of its job-minutes. This frees the doctor slots that went to `markdown-oneline` (#920), `drift-check` (#831) and githubai/bashcrawl CI (#886).
