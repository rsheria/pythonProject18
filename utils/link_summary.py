from dataclasses import dataclass, field
from collections import Counter

@dataclass
class LinkCheckSummary:
    """Track per-row statuses and format a summary string."""

    replaced: int = 0
    row_statuses: dict[int, str] = field(default_factory=dict)
    counts: Counter = field(
        default_factory=lambda: Counter({"ONLINE": 0, "OFFLINE": 0, "UNKNOWN": 0})
    )

    def update(self, row: int, status: str, replaced: bool = False) -> None:
        """Record *status* for *row* and optionally increment replaced count."""
        status = (status or "UNKNOWN").upper()
        prev = self.row_statuses.get(row)
        if prev:
            self.counts[prev] -= 1
        self.row_statuses[row] = status
        self.counts[status] += 1
        if replaced:
            self.replaced += 1

    def message(self, cancelled: bool = False) -> str:
        """Return a formatted summary string."""
        prefix = "Link check cancelled" if cancelled else "Link check finished"
        rows = len(self.row_statuses)
        return (
            f"{prefix}: {rows} rows, replaced {self.replaced}, "
            f"ONLINE {self.counts['ONLINE']}, OFFLINE {self.counts['OFFLINE']}, "
            f"UNKNOWN {self.counts['UNKNOWN']}"
        )