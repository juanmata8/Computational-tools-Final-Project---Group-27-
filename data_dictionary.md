# Data dictionary

## `canada_parliament_votes.csv`

The six required columns are `member_id` (official House `PersonId`), `vote_id`
(`parliament-session-division`), `vote` (`Yes`, `No`, `Paired`, `Abstained`,
`Other:<source value>`, or `Unknown`), `party` (the dated
`CaucusShortName` in the vote record), `date` (ISO division date), and `topic`.
`topic` is blank unless supplied through a separately reviewed topic mapping.

## Supplementary files

- `votes_metadata.csv`: one row per division, including the original division
  number, session, date, subject, document type, bill number, source URL, and
  topic provenance.
- `members_metadata.csv`: observed member/session/party records with official
  member ID, name, constituency, province, and observed party-period dates.
- `voting_matrix.csv`: substantive votes only; `1` is Yes, `-1` is No, and
  blank is unobserved/non-substantive.
- `party_dissent.csv`: substantive member votes, party majority, participation,
  tie flag, and dissent indicator. Tied party votes have no majority.
- `apriori_transactions.csv`: one transaction per vote-party pair containing
  pipe-separated dissenting member IDs. Different parties are never combined.
- `data_quality_report.csv`: missingness, duplicate, coverage, and session
  counts.

## Method decisions

The official participant feed does not enumerate every absent MP; absence is
therefore represented as an unobserved matrix cell, not as `No`. Paired votes
are retained in the long table but excluded from agreement and party-majority
calculations. Party affiliation comes from the participant record for that
division, rather than a current member lookup. The House feed supplies document
types and vote subjects but no consistent policy-area taxonomy, so no topic
labels are invented. The notebook should be rerun when the official source
changes; raw XML is cached to support auditability.
