"""Mission Database (built in the next step)."""

from app.ui.kit import ToolPage


class MissionsView(ToolPage):
    def __init__(self, channel: str, parent=None):
        super().__init__("missions", "Mission Database", "Every mission in the game")
        self.show_empty("Mission Database", "Coming in this update.")
