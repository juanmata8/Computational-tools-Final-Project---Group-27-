# HTML versus participant XML: representative sample

Sample size: 30 votes (six per Parliament, early/middle/late divisions; sample member comparisons: 9086).

## Recommendation

**B. Use XML for participant-level voting records and HTML for vote descriptions and motion text.**

## Quantified sample results

- Member sets equal: 30/30 votes.
- Stable member IDs: HTML profile-link IDs matched XML `PersonId` for every compared member.
- Names: 9086/9086 (100.0%).
- Party affiliation: 9086/9086 (100.0%).
- Vote choices, including paired handling: 9086/9086 (100.0%).
- Paired flags: 9086/9086 (100.0%).
- Constituency: 9086/9086 (100.0%).
- Province: 9086/9086 (100.0%).
- HTML subject present: 30/30 votes.
- HTML motion text present: 30/30 votes.
- HTML date present in title: 30/30 votes.
- Embedded structured participant/application data found: 0/30 pages.

## Field recommendation

| Field | HTML | XML | Recommendation |
|---|---|---|---|
| Parliament/session/division | Vote title | Participant fields | HTML is readable; XML is machine-readable |
| Date | Vote title | `DecisionEventDateTime` | Keep XML date, validate against HTML title |
| Subject | `#mip-vote-desc` | Not reliable in participant XML | Use HTML |
| Motion text | `#mip-vote-text-collapsible-text` | Not present in participant XML | Use HTML |
| Bill number/title | Bill section when applicable | Not reliable in participant XML | Use HTML/LEGISinfo when needed |
| MP ID/name | Profile link/name | `PersonId`/name | Keep XML; HTML links provide cross-check |
| Vote choice/paired | Table columns | Explicit flags and value | Keep XML; HTML paired column is a validation source |
| Party | Political-affiliation table | `CaucusShortName` | Keep XML; HTML agrees in sample |
| Constituency | Member cell | Explicit field | Keep XML; HTML agrees in sample |
| Province | Province-view table | Explicit field | Keep XML; HTML requires a second-table join |

## Conclusion

HTML should not replace participant XML. It contains enough information to reconstruct the records, but it is duplicated presentation HTML, requires joining multiple table views, and encodes paired votes less explicitly. Use XML as the participant-level source and HTML only for descriptive metadata and motion text. No embedded structured data was found in the 30 sampled pages.