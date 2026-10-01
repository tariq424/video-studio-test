"""Extra vertical motion clips for the teaser short (LTX on WanGP)."""
import shutil, time
from pathlib import Path
from studio import config, media
from studio.render import STYLE
from studio.wangp import WanGP
D = Path(r"F:\videos\explainer_studio\shorts\moonshots_teaser_v2\motion"); D.mkdir(parents=True, exist_ok=True)
cfg = config.load(); wg = WanGP(cfg["wangp_mcp"])
log = lambda m: print(time.strftime("%H:%M:%S"), m, flush=True)
CLIPS_OLD = {
 "brain": "Slow push-in on a glowing translucent human brain made of fine light filaments floating in darkness, pulses of light travelling along neural pathways",
 "valley": "Slow rising crane shot over a sunlit green valley with rows of solar panels and wind turbines turning at golden hour, birds gliding, no people",
 "sunrise": "Slow push toward a modern city skyline at sunrise, the sun rising between towers, warm light sweeping across glass buildings, light haze, no people",
 "servers": "Slow dolly between rows of server racks with blinking status lights, red warning light pulsing and sweeping across the aisle, no people, no text",
}
CLIPS = {
 "brain_l": "Slow push-in on a glowing translucent human brain made of fine light filaments floating in darkness, pulses of light travelling along neural pathways",
 "valley_l": "Slow rising crane shot over a sunlit green valley with rows of solar panels and wind turbines turning at golden hour, birds gliding, no people",
 "sunrise_l": "Slow push toward a modern city skyline at sunrise, the sun rising between towers, warm light sweeping across glass buildings, light haze, no people",
 "servers_l": "Slow dolly between rows of server racks with blinking status lights, a red warning light pulsing across the aisle, no people",
}
seed = 5300
for name, prompt in CLIPS.items():
    seed += 1; out = D / f"{name}.mp4"
    if media.ok(out): continue
    r = wg.gen({"model_type": cfg["video_model"], "prompt": prompt + STYLE, "resolution": "1280x720",
                "video_length": 121, "num_inference_steps": 8, "seed": seed, "negative_prompt": "text, captions, subtitles, letters, words, watermark, logo, title"}, log, f"motion {name}")
    if r["ok"]: shutil.copy(r["file"], out); log(f"motion {name} done")
    else: log(f"motion {name} FAILED {r['err']}")
log("TEASER_MOTION_DONE")
