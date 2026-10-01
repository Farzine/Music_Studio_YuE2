# Test fixtures

`yue2_full.reference.json` is the original reference graph from repository commit
`b326eea` (Git blob `9e0651a38aa8bd4c2c6e0bc08e67e494bb0a22d4`). Its exact bytes
are retained for workflow-mapping parity tests. Commit `dbfd0af` removed the
optional root runtime graph; tests no longer require that user installation file.
The fixture is never selected as an application runtime workflow automatically.
