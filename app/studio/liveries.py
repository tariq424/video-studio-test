"""Simplified airline liveries for code-drawn aircraft (physics `aircraft_flight` sim, flat illustrations).

One entry per airline: colours + tail design + fuselage look. Recognisable by colour and tail shape only: no logos, no lettering,
no registrations (the video labels the shot as a simulation / illustration anyway). pick() reads the narration (and the beat's
subject) and returns the airline's livery, or None -> the renderer draws the generic airliner.

Fields (all colours hex):
  body      upper fuselage            belly    lower fuselage / cheatline below the windows
  stripe    cheatline along the windows ("" = none)
  tail      main tail colour          tail2    second tail colour ("" = none)
  tail_art  how tail + tail2 combine: "solid" | "split" (diagonal: tail2 at the back) | "band" (tail2 band across the middle)
            | "arc" (tail2 sweep from the root to the tip) | "flag" (tail2 + tail3 horizontal stripes over tail)
  tail3     third tail colour (only "flag")
  engine    engine nacelles           wingtip  winglet colour ("" = same as the wing)
Add an airline: one entry here + its names in `names` (regex, matched case-insensitively against narration + subject)."""
import re

AIRLINES = {
    "flydubai": {"names": r"fly ?dubai", "body": "#ffffff", "belly": "#1b4e9b", "stripe": "#f26b21",
                 "tail": "#1b4e9b", "tail2": "#f26b21", "tail_art": "split", "engine": "#f26b21", "wingtip": "#f26b21"},
    "emirates": {"names": r"emirates", "body": "#ffffff", "belly": "#e8e4dc", "stripe": "",
                 "tail": "#ffffff", "tail2": "#d71a21", "tail3": "#00843d", "tail_art": "flag", "engine": "#ffffff", "wingtip": "#d71a21"},
    "qatar": {"names": r"qatar airways|\bqatar\b(?= (flight|jet|plane|airliner|aircraft))", "body": "#e9e7e3", "belly": "#d8d4cf", "stripe": "",
              "tail": "#5c0632", "tail2": "", "tail_art": "solid", "engine": "#5c0632", "wingtip": "#5c0632"},
    "elal": {"names": r"el ?al", "body": "#ffffff", "belly": "#ffffff", "stripe": "#0e3b8f",
             "tail": "#ffffff", "tail2": "#0e3b8f", "tail_art": "band", "engine": "#0e3b8f", "wingtip": "#0e3b8f"},
    "ryanair": {"names": r"ryanair", "body": "#ffffff", "belly": "#073590", "stripe": "",
                "tail": "#073590", "tail2": "#f1c933", "tail_art": "arc", "engine": "#073590", "wingtip": "#f1c933"},
    "easyjet": {"names": r"easy ?jet", "body": "#ffffff", "belly": "#ffffff", "stripe": "",
                "tail": "#ff6600", "tail2": "", "tail_art": "solid", "engine": "#ff6600", "wingtip": "#ff6600"},
    "lufthansa": {"names": r"lufthansa", "body": "#ffffff", "belly": "#ffffff", "stripe": "",
                  "tail": "#05164d", "tail2": "#ffffff", "tail_art": "band", "engine": "#05164d", "wingtip": "#05164d"},
    "united": {"names": r"united airlines", "body": "#ffffff", "belly": "#00205b", "stripe": "#0a5bd8",
               "tail": "#00205b", "tail2": "#0a5bd8", "tail_art": "arc", "engine": "#00205b", "wingtip": "#00205b"},
    "american": {"names": r"american airlines", "body": "#c9ced4", "belly": "#9aa3ab", "stripe": "",
                 "tail": "#0078d2", "tail2": "#c30019", "tail3": "#ffffff", "tail_art": "flag", "engine": "#c9ced4", "wingtip": "#0078d2"},
    "delta": {"names": r"delta (air ?lines|flight|jet|plane)", "body": "#ffffff", "belly": "#003a70", "stripe": "",
              "tail": "#003a70", "tail2": "#c01933", "tail_art": "arc", "engine": "#003a70", "wingtip": "#003a70"},
    "southwest": {"names": r"southwest", "body": "#304cb2", "belly": "#304cb2", "stripe": "#ffbf27",
                  "tail": "#304cb2", "tail2": "#c8102e", "tail_art": "arc", "engine": "#304cb2", "wingtip": "#ffbf27"},
    "turkish": {"names": r"turkish airlines", "body": "#ffffff", "belly": "#ffffff", "stripe": "",
                "tail": "#c70a0c", "tail2": "", "tail_art": "solid", "engine": "#c70a0c", "wingtip": "#c70a0c"},
    "air india": {"names": r"air india", "body": "#ffffff", "belly": "#ffffff", "stripe": "#da0e29",
                  "tail": "#da0e29", "tail2": "#7a1fa2", "tail_art": "arc", "engine": "#da0e29", "wingtip": "#e8b33a"},
}


def pick(*texts):
    """-> {"key", ...colours} for the airline named in the first text that names one, or None (generic airliner).
    Callers pass, in order: the narration, the beat's subject (name + brand), the story's entities - so "the aircraft dropped" in
    a flydubai story is drawn as flydubai, while a beat that names another airline gets that one."""
    for t in texts:
        for key, lv in AIRLINES.items():
            if re.search(r"\b(" + lv["names"] + r")", t or "", re.I):
                return {"key": key, **{k: v for k, v in lv.items() if k != "names"}}
    return None


def story_text(ents):
    """The story's named things (coherence entities) as one string for pick()'s last fallback."""
    return " ".join(f"{e.get('name', '')} {e.get('brand', '')}" for e in (ents or []) if isinstance(e, dict))
