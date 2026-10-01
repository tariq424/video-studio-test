import yt_dlp, sys, json
from studio import transcript
from pathlib import Path
meta, text = transcript.fetch("https://youtu.be/deg8bOoziaE", Path(r"F:\videos\explainer_studio\_research\deg8bOoziaE"), print)
print("TITLE:", meta["title"], "|", meta["channel"], "|", (meta["duration"] or 0)//60, "min")
