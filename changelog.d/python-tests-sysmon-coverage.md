### Changed

- `python-tests.yml`: the test shards run under `COVERAGE_CORE=sysmon` (Python 3.12's `sys.monitoring`) instead of coverage's default tracer. Same tests, same advisory coverage table; the console, pages and spec files ran 2.2 to 2.5 times slower under the old tracer, and the change is measured at about 40% less test time on the named shards, the hub's largest single use of Actions minutes.
