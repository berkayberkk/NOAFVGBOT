"""
NOAFVGBOT V2.6 — Grouped Chronological Dataset Splitter.

Splits research rows chronologically by ParentThesis groups (train / validation / test)
to prevent same-thesis information leakage across dataset splits.

INVARIANTS:
- Chronological ordering by earliest candidate timestamp per thesis.
- No shuffle.
- All child candidates belonging to the same ParentThesis stay in the SAME split.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from research.v2.dataset.schema import ResearchRow


@dataclass(frozen=True)
class DatasetSplit:
    train_rows: List[ResearchRow]
    validation_rows: List[ResearchRow]
    test_rows: List[ResearchRow]


class GroupedChronologicalSplitter:
    """Splits research rows chronologically by ParentThesis groups."""

    def __init__(self, train_ratio: float = 0.70, val_ratio: float = 0.15, test_ratio: float = 0.15):
        if abs((train_ratio + val_ratio + test_ratio) - 1.0) > 1e-4:
            raise ValueError(f"Split ratios must sum to 1.0, got: {train_ratio} + {val_ratio} + {test_ratio}")
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.test_ratio = test_ratio

    def split(self, rows: List[ResearchRow]) -> DatasetSplit:
        """Splits research rows chronologically by thesis_id groups."""
        if not rows:
            return DatasetSplit(train_rows=[], validation_rows=[], test_rows=[])

        # 1. Group rows by thesis_id
        thesis_groups: Dict[str, List[ResearchRow]] = {}
        for r in rows:
            tid = r.id_fields["thesis_id"]
            if tid not in thesis_groups:
                thesis_groups[tid] = []
            thesis_groups[tid].append(r)

        # 2. Sort thesis groups by earliest candidate timestamp
        def get_group_earliest_dt(group: List[ResearchRow]) -> datetime:
            min_ts = min(r.id_fields["candidate_created_at"] for r in group)
            return datetime.fromisoformat(min_ts).replace(tzinfo=timezone.utc)

        sorted_theses = sorted(thesis_groups.keys(), key=lambda tid: (get_group_earliest_dt(thesis_groups[tid]), tid))

        num_theses = len(sorted_theses)
        n_train = int(num_theses * self.train_ratio)
        n_val = int(num_theses * self.val_ratio)

        train_theses = set(sorted_theses[:n_train])
        val_theses = set(sorted_theses[n_train:n_train + n_val])
        test_theses = set(sorted_theses[n_train + n_val:])

        train_rows: List[ResearchRow] = []
        val_rows: List[ResearchRow] = []
        test_rows: List[ResearchRow] = []

        for r in rows:
            tid = r.id_fields["thesis_id"]
            if tid in train_theses:
                train_rows.append(r)
            elif tid in val_theses:
                val_rows.append(r)
            else:
                test_rows.append(r)

        return DatasetSplit(
            train_rows=train_rows,
            validation_rows=val_rows,
            test_rows=test_rows,
        )
