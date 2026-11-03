# Canadian Parliament Voting Behaviour

This project studies how party alignment and dissent vary across Canadian
House of Commons votes over time. The research question is: **how does party
alignment vary across policy topics in the Canadian Parliament, as shown by
voting agreement and party dissent?**

The pipeline uses official House of Commons vote records for Parliaments
41–45 (approximately 2011 to the latest available division). It preserves
official member IDs and the caucus recorded for each vote. Recorded `Yes`,
`No`, paired and other vote values remain distinct; an absent member is not
silently treated as voting `No`. Topics remain blank unless a reviewed topic
mapping is supplied.

## Repository structure

```text
.
├── data/
│   ├── raw/                 # local source cache; ignored by Git
│   ├── processed/           # reproducible pipeline outputs; versionable
│   └── processed_clean/     # Week 1 cleaned analysis outputs
├── notebooks/
│   └── week1_canadian_parliament_preprocessing.ipynb
├── reports/figures/
├── scripts/run_pipeline.py
├── src/canadian_parliament/
│   ├── config.py            # repository-independent paths
│   └── preprocessing.py     # collection and transformation pipeline
├── tests/
├── data_dictionary.md
├── pyproject.toml
└── uv.lock
```

`data/processed/` contains MP-vote records, vote metadata, member metadata,
voting matrices, party dissent, Apriori transactions and data-quality reports.
The notebook reads those outputs and writes its cleaned variants to
`data/processed_clean/`.

## Setup with uv

Install uv using the [official installation instructions](https://docs.astral.sh/uv/getting-started/installation/)
if it is not already available. From the repository root:

```powershell
uv sync
```

`uv sync` creates or updates the project environment from `pyproject.toml` and
the committed `uv.lock`. The project supports Python 3.10 through 3.14; the
repository's `.python-version` selects Python 3.12 when available.

## Raw data and pipeline

Raw XML and HTML source responses belong in `data/raw/`. The directory is
intentionally excluded from Git; `data/raw/README.md` documents this policy.
The downloader caches responses there and does not need to redownload valid
cached files.

To collect missing official source data and regenerate the processed datasets:

```powershell
uv run python scripts/run_pipeline.py
```

The same entry point is available as:

```powershell
uv run run-pipeline
```

The pipeline writes these files to `data/processed/` without changing the
analytical definitions in the original project:

- `canada_parliament_votes.csv`
- `votes_metadata.csv`
- `members_metadata.csv`
- `voting_matrix.csv`
- `party_dissent.csv`
- `apriori_transactions.csv`
- `data_quality_report.csv`

The collection step is network-dependent when source files are not already
cached. See [data_dictionary.md](data_dictionary.md) for field definitions and
method decisions.

### Extending the historical coverage

The repository currently includes data for Parliaments 41–45. To add earlier
years, update the `PARLIAMENTS` tuple in
[`src/canadian_parliament/preprocessing.py`](src/canadian_parliament/preprocessing.py).
For example, to include Parliaments 36–40 as well, use:

```python
PARLIAMENTS = (36, 37, 38, 39, 40, 41, 42, 43, 44, 45)
```

Then run the pipeline from the repository root:

```powershell
uv run python scripts\run_pipeline.py
```

The pipeline retrieves and caches the official participant XML and vote-detail
HTML sources under `data/raw/`. It processes those sources and updates the
defined CSV outputs under `data/processed/`, including the MP-vote records,
vote metadata, member metadata, voting matrix, party dissent, Apriori
transactions and data-quality report. Raw source files are intentionally
ignored by Git, while the processed CSV files remain eligible for version
control. Extending the Parliament tuple changes the coverage of the generated
files; preserve a copy of existing processed outputs if you need to compare
different coverage ranges.

## Week 1 notebook

Launch Jupyter from the project environment and open
[week1_canadian_parliament_preprocessing.ipynb](notebooks/week1_canadian_parliament_preprocessing.ipynb):

```powershell
uv run jupyter lab
```

Run the notebook from the repository root. It uses the same uv environment,
loads `data/processed/`, preserves its explanations, analysis and figures, and
writes cleaned outputs to `data/processed_clean/`. It does not overwrite raw
data or the original processed datasets.

## Tests

Run the focused preprocessing tests with:

```powershell
uv run pytest
```

## Version-control policy

The committed repository includes source code, the notebook, documentation,
tests, `pyproject.toml`, `.python-version`, `uv.lock`, and the processed
datasets that support analysis. Raw downloaded source files, Python caches,
virtual environments, notebook checkpoints, logs, test caches and generated
figures are excluded by `.gitignore`. Processed data is deliberately **not**
ignored so it remains shareable and reviewable.
