"""Curated seeds for the point-in-time universe (D5, §4.6.4).

`index_membership.csv` is drafted by `sr universe draft` (pinned Wikipedia
revisions) and **verified by hand** before promotion; the CI test
`test_universe_gate` skips until the file exists and passes its gate.
schema: index_name,ticker_at_time,security_id,cik_or_hkex_code,start_date,end_date,source_url,evidence_grade
"""

from __future__ import annotations
