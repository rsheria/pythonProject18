"""GUI package initialization with global widget customizations."""

from PyQt5 import QtWidgets


class HiddenProgressBar(QtWidgets.QProgressBar):
    """Progress bar that remains hidden regardless of updates."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        super().setVisible(False)

    def show(self):  # pragma: no cover - trivial override
        """Ignore requests to show the widget."""
        pass

    def setVisible(self, _visible):  # pragma: no cover - trivial override
        """Force the widget to stay hidden."""
        super().setVisible(False)


# Replace the standard QProgressBar globally so legacy progress bars remain hidden
QtWidgets.QProgressBar = HiddenProgressBar