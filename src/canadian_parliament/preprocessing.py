"""Reproducible extraction and preprocessing for House of Commons divisions.

The script deliberately does not infer policy topics.  The House vote feed
provides a document type and a division subject, but not a consistent policy
taxonomy.  Topic is therefore left missing unless the researcher supplies a
reviewed topic file.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import requests

from .config import PROCESSED_DATA_DIR, RAW_DATA_DIR


BASE_URL = "https://www.ourcommons.ca"
SOURCE_VOTES = f"{BASE_URL}/Members/en/votes"
SOURCE_MEMBERS = f"{BASE_URL}/Members/en/search/XML"
PARLIAMENTS = (41, 42, 43, 44, 45)
MAX_DIVISION = 1000
MAX_CONSECUTIVE_MISSES = 30
REQUEST_DELAY_SECONDS = 0.1
MAIN_COLUMNS = ["member_id", "vote_id", "vote", "party", "date", "topic"]


def _text(element: ET.Element | None, default: str = "") -> str:
    return (element.text or "").strip() if element is not None else default


def _bool(value: str) -> bool:
    return value.strip().lower() == "true"


def standardize_vote(row: dict[str, str]) -> str:
    if _bool(row.get("IsVoteYea", "")):
        return "Yes"
    if _bool(row.get("IsVoteNay", "")):
        return "No"
    raw = row.get("VoteValueName", "").strip()
    if raw:
        normalized = raw.casefold()
        if "pair" in normalized:
            return "Paired"
        if "abstain" in normalized:
            return "Abstained"
        return f"Other:{raw}"
    return "Unknown"


def vote_id(parliament: str, session: str, division: str) -> str:
    return f"{parliament}-{session}-{division}"


def parse_vote_summary(xml_bytes: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(xml_bytes)
    records: list[dict[str, str]] = []
    for element in root.findall(".//Vote"):
        record = {child.tag: _text(child) for child in element}
        record["vote_id"] = vote_id(
            record.get("ParliamentNumber", ""),
            record.get("SessionNumber", ""),
            record.get("DecisionDivisionNumber", ""),
        )
        records.append(record)
    return records


def parse_participants(xml_bytes: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(xml_bytes)
    return [
        {child.tag: _text(child) for child in element}
        for element in root.findall(".//VoteParticipant")
    ]


MAX_WORKERS = 6
MAX_RETRIES = 3


def download_one(url, raw_path):
    raw_path = Path(raw_path)

    # Resume: do not download files already saved and validated.
    if raw_path.exists():
        try:
            ET.fromstring(raw_path.read_bytes())
            return raw_path.read_bytes()
        except ET.ParseError:
            raw_path.unlink(missing_ok=True)

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(
                url,
                timeout=60,
                headers={
                    "User-Agent": "canadian-parliament-vote-study/1.0"
                },
            )

            if response.status_code == 404:
                return None

            response.raise_for_status()

            content = response.content

            # Check that the response is valid XML before saving.
            ET.fromstring(content)

            temp_path = raw_path.with_suffix(".tmp")
            temp_path.write_bytes(content)
            temp_path.replace(raw_path)

            return content

        except (requests.RequestException, ET.ParseError):
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(2 ** attempt)

    return None


def get_xml(session: requests.Session, url: str) -> bytes | None:
    """Fetch one XML resource for the non-parallel summary endpoint."""
    response = session.get(url, timeout=60)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content


def _clean_html_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"\s+([,.;:!?])", r"\1", value)


def parse_vote_detail_html(html: bytes | str) -> dict[str, str]:
    """Extract descriptive fields from an official vote detail page."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    subject_node = soup.find(id="mip-vote-desc")
    motion_node = soup.find(id="mip-vote-text-collapsible-text")
    bill_node = soup.find(class_="mip-vote-bill-section")
    subject = _clean_html_text(subject_node.get_text(" ", strip=True)) if subject_node else ""
    motion_text = _clean_html_text(motion_node.get_text(" ", strip=True)) if motion_node else ""
    bill_number = ""
    bill_title = ""
    document_type = ""
    if bill_node:
        heading = bill_node.find(["h2", "h3"])
        if heading:
            heading_text = _clean_html_text(heading.get_text(" ", strip=True))
            if re.fullmatch(r"[CS]-\d+", heading_text):
                bill_number = heading_text
                title_node = bill_node.find_all("p")[0] if bill_node.find_all("p") else None
                if title_node:
                    bill_title = _clean_html_text(title_node.get_text(" ", strip=True))
        if not bill_number:
            match = re.search(r"\b([CS]-\d+)\b", bill_node.get_text(" ", strip=True))
            if match:
                bill_number = match.group(1)
    if subject:
        prefix = subject.split(" ", 1)[0]
        document_type = {
            "Opposition": "Supply",
            "Government": "Legislative Process",
            "Private": "Legislative Process",
            "Senate": "Legislative Process",
        }.get(prefix, "")
    return {
        "subject": subject,
        "motion_text": motion_text,
        "bill_number": bill_number,
        "bill_title": bill_title,
        "document_type": document_type,
    }


def fetch_vote_detail_metadata(
    metadata: list[dict[str, str]],
    raw_dir: str | Path,
) -> tuple[list[dict[str, str]], pd.DataFrame]:
    """Enrich vote metadata from cached/downloaded official detail pages."""
    raw_path = Path(raw_dir) / "vote_pages"
    raw_path.mkdir(parents=True, exist_ok=True)
    enriched: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []

    def fetch_one(row: dict[str, str]) -> tuple[dict[str, str], str | None]:
        page_path = raw_path / f"{row['vote_id'].replace('-', '_')}.html"
        try:
            if page_path.exists():
                html = page_path.read_bytes()
            else:
                response = requests.get(
                    row["source_url"],
                    headers={"User-Agent": "canadian-parliament-vote-study/1.0"},
                    timeout=60,
                )
                response.raise_for_status()
                html = response.content
                page_path.write_bytes(html)
            fields = parse_vote_detail_html(html)
            result = row.copy()
            result.update(fields)
            if not result.get("document_type"):
                result["document_type"] = row.get("document_type", "")
            result["metadata_source"] = "official vote detail page"
            result["metadata_fetch_error"] = ""
            return result, None
        except (OSError, requests.RequestException, ValueError) as error:
            result = row.copy()
            result.setdefault("subject", "")
            result.setdefault("motion_text", "")
            result.setdefault("bill_number", "")
            result.setdefault("bill_title", "")
            result.setdefault("document_type", "")
            result["metadata_source"] = "official vote detail page unavailable"
            result["metadata_fetch_error"] = str(error)
            return result, str(error)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(fetch_one, row) for row in metadata]
        for future in as_completed(futures):
            row, error = future.result()
            if error:
                failures.append({
                    "vote_id": row["vote_id"],
                    "parliament": row.get("parliament", ""),
                    "session": row.get("session", ""),
                    "error": error,
                })
            enriched.append(row)
    return enriched, pd.DataFrame(failures)


def discover_divisions_parallel(
    parliament,
    session_number,
    raw_dir,
    max_division=1000,
):
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    jobs = {}

    for division in range(1, max_division + 1):
        url = (
            f"{SOURCE_VOTES}/{parliament}/"
            f"{session_number}/{division}/XML"
        )

        raw_path = raw_dir / (
            f"vote_{parliament}_{session_number}_{division}.xml"
        )

        jobs[division] = (url, raw_path)

    participants = []
    metadata = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(download_one, url, path): division
            for division, (url, path) in jobs.items()
        }

        for future in as_completed(futures):
            division = futures[future]

            try:
                content = future.result()
            except Exception as error:
                print(f"Failed: {parliament}/{session_number}/{division}: {error}")
                continue

            if content is None:
                continue

            rows = parse_participants(content)

            for row in rows:
                row["vote_id"] = vote_id(
                    str(parliament),
                    str(session_number),
                    str(division),
                )

            participants.extend(rows)

            if rows:
                first = rows[0]

                metadata.append({
                    "vote_id": vote_id(
                        str(parliament),
                        str(session_number),
                        str(division),
                    ),
                    "parliament": str(parliament),
                    "session": str(session_number),
                    "date": first.get("DecisionEventDateTime", "")[:10],
                    "result": first.get("DecisionResultName", ""),
                    "subject": "",
                    "motion_text": "",
                    "bill_number": "",
                    "bill_title": "",
                    "document_type": "",
                    "metadata_source": "official vote detail page pending",
                    "metadata_fetch_error": "",
                    "source_url": (
                        f"{SOURCE_VOTES}/{parliament}/"
                        f"{session_number}/{division}"
                    ),
                })

    return participants, metadata


def discover_divisions_until_empty(
    parliament,
    session_number,
    raw_dir,
    max_division=MAX_DIVISION,
):
    """Download divisions in order and stop at the first empty XML response.

    The numbered House endpoint returns HTTP 200 with an empty participant
    collection after the final division, so continuing past that point only
    creates unnecessary requests.
    """
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    participants = []
    metadata = []

    for division in range(1, max_division + 1):
        url = (
            f"{SOURCE_VOTES}/{parliament}/"
            f"{session_number}/{division}/XML"
        )
        raw_path = raw_dir / (
            f"vote_{parliament}_{session_number}_{division}.xml"
        )
        try:
            content = download_one(url, raw_path)
        except Exception as error:
            print(f"Failed: {parliament}/{session_number}/{division}: {error}")
            raise

        if content is None:
            break

        rows = parse_participants(content)
        if not rows:
            break

        current_vote_id = vote_id(
            str(parliament),
            str(session_number),
            str(division),
        )
        for row in rows:
            row["vote_id"] = current_vote_id
        participants.extend(rows)

        first = rows[0]
        metadata.append({
            "vote_id": current_vote_id,
            "parliament": str(parliament),
            "session": str(session_number),
            "date": first.get("DecisionEventDateTime", "")[:10],
            "result": first.get("DecisionResultName", ""),
            "source_url": (
                f"{SOURCE_VOTES}/{parliament}/"
                f"{session_number}/{division}"
            ),
        })

    if len(metadata) == max_division:
        print(
            f"Warning: {parliament}/{session_number} reached "
            f"max_division={max_division}; coverage may be truncated."
        )

    return participants, metadata


def fetch_data(
    raw_dir: str | Path = RAW_DATA_DIR,
    parliaments: tuple[int, ...] = PARLIAMENTS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_path = Path(raw_dir)
    raw_path.mkdir(parents=True, exist_ok=True)
    all_participants: list[dict[str, str]] = []
    all_metadata: dict[str, dict[str, str]] = {}
    with requests.Session() as session:
        session.headers["User-Agent"] = "canadian-parliament-vote-study/1.0"
        for parliament in parliaments:
            # This endpoint is an efficient source for the current Parliament.
            index_url = f"{SOURCE_VOTES}/XML"
            index_path = raw_path / f"votes_index_{parliament}.xml"
            if parliament == max(parliaments):
                if not index_path.exists():
                    content = get_xml(session, index_url)
                    if content is not None:
                        index_path.write_bytes(content)
                if index_path.exists():
                    for summary in parse_vote_summary(index_path.read_bytes()):
                        if summary.get("ParliamentNumber") == str(parliament):
                            all_metadata[summary["vote_id"]] = {
                                "vote_id": summary["vote_id"],
                                "original_division_id": summary.get("DecisionDivisionNumber", ""),
                                "parliament": summary.get("ParliamentNumber", ""),
                                "session": summary.get("SessionNumber", ""),
                                "date": summary.get("DecisionEventDateTime", "")[:10],
                                "bill_number": summary.get("BillNumberCode", ""),
                                "bill_title": "",
                                "subject": summary.get("DecisionDivisionSubject", ""),
                                "motion_text": "",
                                "document_type": summary.get("DecisionDivisionDocumentTypeName", ""),
                                "motion_description": summary.get("DecisionDivisionSubject", ""),
                                "vote_question": summary.get("DecisionDivisionSubject", ""),
                                "topic": "",
                                "topic_source": "not provided by House vote feed",
                                "metadata_source": "official vote summary XML",
                                "metadata_fetch_error": "",
                                "source_url": f"{SOURCE_VOTES}/{parliament}/{summary.get('SessionNumber')}/{summary.get('DecisionDivisionNumber')}",
                            }
                    sessions = sorted({
                        int(x["session"])
                        for x in all_metadata.values()
                        if x.get("parliament") == str(parliament)
                        and x.get("session")
                    })
                else:
                    sessions = [1, 2]
            else:
                sessions = [1, 2]
            for session_number in sessions:
                rows, metadata = discover_divisions_until_empty(
                    parliament, session_number, raw_path
                )
                all_participants.extend(rows)
                for row in metadata:
                    all_metadata.setdefault(row["vote_id"], row)
    enriched_metadata, metadata_failures = fetch_vote_detail_metadata(
        list(all_metadata.values()), raw_path
    )
    participant_df = pd.DataFrame(all_participants)
    metadata_df = pd.DataFrame(enriched_metadata)
    if not metadata_failures.empty:
        failure_map = metadata_failures.set_index("vote_id")["error"]
        metadata_df["metadata_fetch_error"] = (
            metadata_df["vote_id"].map(failure_map).fillna(
                metadata_df["metadata_fetch_error"]
            )
        )
    return participant_df, metadata_df


def prepare_main(
    participants: pd.DataFrame,
    metadata: pd.DataFrame,
    reviewed_topics: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if participants.empty:
        return pd.DataFrame(columns=MAIN_COLUMNS)
    result = participants.copy()
    result["member_id"] = result["PersonId"].replace("", pd.NA)
    result["vote_id"] = result["vote_id"].replace("", pd.NA)
    result["vote"] = result.apply(standardize_vote, axis=1)
    result["party"] = result["CaucusShortName"].replace("", "Unknown")
    result["date"] = pd.to_datetime(
        result["DecisionEventDateTime"], errors="coerce", utc=True
    ).dt.strftime("%Y-%m-%d")
    result = result.merge(metadata[["vote_id", "topic"]], on="vote_id", how="left")
    if reviewed_topics is not None and not reviewed_topics.empty:
        result = result.drop(columns=["topic"]).merge(
            reviewed_topics[["vote_id", "topic"]], on="vote_id", how="left"
        )
    return result[MAIN_COLUMNS].drop_duplicates(["member_id", "vote_id"])


def prepare_members_metadata(participants: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "member_id", "full_name", "constituency", "province", "party",
        "party_start_date", "party_end_date", "parliamentary_session",
    ]
    if participants.empty:
        return pd.DataFrame(columns=columns)
    result = participants.copy()
    result["member_id"] = result["PersonId"]
    result["full_name"] = (
        result["PersonOfficialFirstName"] + " " + result["PersonOfficialLastName"]
    ).str.strip()
    result["party_start_date"] = result["DecisionEventDateTime"].str[:10]
    result["parliamentary_session"] = (
        result["ParliamentNumber"] + "/" + result["SessionNumber"]
    )
    result["party_end_date"] = ""
    return result.rename(
        columns={
            "ConstituencyName": "constituency",
            "ConstituencyProvinceTerritoryName": "province",
            "CaucusShortName": "party",
        }
    )[columns].drop_duplicates()


def prepare_matrix(main: pd.DataFrame) -> pd.DataFrame:
    substantive = main[main["vote"].isin(["Yes", "No"])].copy()
    substantive["value"] = substantive["vote"].map({"Yes": 1, "No": -1})
    return substantive.pivot(index="member_id", columns="vote_id", values="value")


def prepare_dissent(main: pd.DataFrame) -> pd.DataFrame:
    substantive = main[main["vote"].isin(["Yes", "No"])].copy()
    counts = (
        substantive.groupby(["vote_id", "party", "vote"]).size()
        .rename("count").reset_index()
    )
    totals = counts.groupby(["vote_id", "party"])["count"].sum().rename("party_participation")
    majority = counts.sort_values("count").drop_duplicates(
        ["vote_id", "party"], keep="last"
    )
    top_counts = counts.groupby(["vote_id", "party"])["count"].transform("max")
    ties = (
        counts.assign(is_top=counts["count"].eq(top_counts))
        .groupby(["vote_id", "party"])["is_top"]
        .sum()
        .gt(1)
    )
    majority = majority.set_index(["vote_id", "party"])["vote"].rename("party_majority_vote")
    result = substantive.merge(majority, on=["vote_id", "party"], how="left")
    result = result.merge(totals, on=["vote_id", "party"], how="left")
    result["majority_tied"] = result.set_index(["vote_id", "party"]).index.map(ties).fillna(False).to_numpy()
    result.loc[result["majority_tied"], "party_majority_vote"] = pd.NA
    result["dissent"] = (
        result["party_majority_vote"].notna()
        & result["vote"].ne(result["party_majority_vote"].fillna(""))
    )
    return result[
        ["member_id", "vote_id", "party", "vote", "party_majority_vote",
         "dissent", "party_participation", "majority_tied"]
    ].rename(columns={"vote": "individual_vote"})


def prepare_transactions(dissent: pd.DataFrame) -> pd.DataFrame:
    rows = dissent[dissent["dissent"]].groupby(
        ["vote_id", "party"]
    )["member_id"].agg(
        lambda values: "|".join(sorted(values.astype(str)))
    ).rename("dissenting_member_ids").reset_index()
    rows.insert(0, "transaction_id", rows["vote_id"] + "|" + rows["party"])
    return rows[
        ["transaction_id", "vote_id", "party", "dissenting_member_ids"]
    ]


def quality_report(main: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in ["member_id", "vote_id", "vote", "party", "date", "topic"]:
        rows.append({"metric": f"missing_{column}", "value": int(main[column].isna().sum())})
    rows.extend([
        {"metric": "duplicate_member_vote", "value": int(main.duplicated(["member_id", "vote_id"]).sum())},
        {"metric": "unique_votes", "value": int(main["vote_id"].nunique())},
        {"metric": "unique_members", "value": int(main["member_id"].nunique())},
        {"metric": "metadata_rows", "value": int(len(metadata))},
    ])
    for column in ["subject", "motion_text", "bill_number", "bill_title", "document_type"]:
        if column in metadata:
            rows.append({
                "metric": f"metadata_missing_{column}",
                "value": int(metadata[column].fillna("").eq("").sum()),
            })
    if "metadata_fetch_error" in metadata:
        rows.append({
            "metric": "metadata_fetch_errors",
            "value": int(metadata["metadata_fetch_error"].fillna("").ne("").sum()),
        })
    if not metadata.empty:
        metadata_sessions = metadata.assign(
            session=metadata["parliament"].astype(str) + "-"
            + metadata["session"].astype(str)
        ).groupby("session").agg(
            metadata_votes=("vote_id", "nunique"),
            missing_subject=("subject", lambda values: values.fillna("").eq("").sum()),
            missing_motion_text=("motion_text", lambda values: values.fillna("").eq("").sum()),
            fetch_errors=("metadata_fetch_error", lambda values: values.fillna("").ne("").sum()),
        )
        for session, values in metadata_sessions.iterrows():
            for measure, value in values.items():
                rows.append({
                    "metric": f"metadata_session_{session}_{measure}",
                    "value": int(value),
                })
    if not main.empty:
        session_counts = main.assign(
            session=main["vote_id"].str.extract(r"^(\d+-\d+)-")[0]
        ).groupby("session").agg(
            votes=("vote_id", "nunique"), members=("member_id", "nunique"),
            records=("vote_id", "size"),
        )
        for session, values in session_counts.iterrows():
            for measure, value in values.items():
                rows.append({"metric": f"session_{session}_{measure}", "value": int(value)})
    return pd.DataFrame(rows)


def run(
    output_dir: str | Path = PROCESSED_DATA_DIR,
    raw_dir: str | Path = RAW_DATA_DIR,
) -> None:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    participants, metadata = fetch_data(raw_dir=raw_dir)
    main = prepare_main(participants, metadata)
    members = prepare_members_metadata(participants)
    matrix = prepare_matrix(main)
    dissent = prepare_dissent(main)
    transactions = prepare_transactions(dissent)
    main.to_csv(output / "canada_parliament_votes.csv", index=False)
    metadata.to_csv(output / "votes_metadata.csv", index=False)
    members.to_csv(output / "members_metadata.csv", index=False)
    matrix.to_csv(output / "voting_matrix.csv")
    dissent.to_csv(output / "party_dissent.csv", index=False)
    transactions.to_csv(output / "apriori_transactions.csv", index=False)
    quality_report(main, metadata).to_csv(output / "data_quality_report.csv", index=False)


if __name__ == "__main__":
    run()
