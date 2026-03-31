# Task 4.0 Proofs — Template Version Detection

## Test Results

```
tests/test_template_version.py::TestCheckTemplateVersion::test_absent_version_triggers_full_enqueue PASSED
tests/test_template_version.py::TestCheckTemplateVersion::test_matching_version_is_noop PASSED
tests/test_template_version.py::TestCheckTemplateVersion::test_stale_version_triggers_full_enqueue PASSED
tests/test_template_version.py::TestCheckTemplateVersion::test_downgrade_is_noop PASSED
tests/test_template_version.py::TestCheckTemplateVersion::test_idempotent_when_matching PASSED
tests/test_template_version.py::TestCheckTemplateVersion::test_empty_library_still_updates_version PASSED

6 passed in 0.04s
```

## Lint Output

```
All checks passed!
```

## Verification Summary

- 6 unit tests covering all template version detection scenarios — all pass
- Absent version (None → treated as 0) triggers full enqueue + meta update
- Matching version is a no-op (no enqueue, no meta update)
- Stale version (stored < current) triggers full re-enqueue + meta update
- Downgrade (stored > current) is a no-op (safe for rollbacks)
- Idempotency: two calls with matching version don't re-enqueue
- Empty library still updates version metadata (no items to enqueue)
- get_template_version() and set_template_version() added to SqliteVecRepository
- check_template_version() integrated into EmbeddingWorker.startup()
