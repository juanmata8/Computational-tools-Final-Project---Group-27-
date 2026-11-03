import pandas as pd

from canadian_parliament.preprocessing import (
    prepare_dissent,
    prepare_matrix,
    prepare_transactions,
    standardize_vote,
)


def test_standardize_vote_preserves_recorded_vote_categories():
    assert standardize_vote({"IsVoteYea": "true"}) == "Yes"
    assert standardize_vote({"IsVoteNay": "true"}) == "No"
    assert standardize_vote({"VoteValueName": "Paired"}) == "Paired"
    assert standardize_vote({"VoteValueName": "Absent"}) == "Other:Absent"
    assert standardize_vote({}) == "Unknown"


def test_matrix_excludes_non_substantive_votes():
    main = pd.DataFrame(
        [
            {"member_id": "1", "vote_id": "41-1-1", "vote": "Yes"},
            {"member_id": "2", "vote_id": "41-1-1", "vote": "No"},
            {"member_id": "3", "vote_id": "41-1-1", "vote": "Paired"},
        ]
    )
    matrix = prepare_matrix(main)
    assert matrix.loc["1", "41-1-1"] == 1
    assert matrix.loc["2", "41-1-1"] == -1
    assert "3" not in matrix.index


def test_dissent_and_transactions_are_party_scoped():
    main = pd.DataFrame(
        [
            {"member_id": "1", "vote_id": "41-1-1", "party": "A", "vote": "Yes"},
            {"member_id": "2", "vote_id": "41-1-1", "party": "A", "vote": "Yes"},
            {"member_id": "3", "vote_id": "41-1-1", "party": "A", "vote": "No"},
            {"member_id": "4", "vote_id": "41-1-1", "party": "B", "vote": "No"},
        ]
    )
    dissent = prepare_dissent(main)
    transactions = prepare_transactions(dissent)
    assert dissent.loc[dissent["member_id"] == "3", "dissent"].item()
    assert transactions["party"].tolist() == ["A"]
    assert transactions["dissenting_member_ids"].tolist() == ["3"]
