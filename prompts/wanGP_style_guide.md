# WanGP image prompt style guide

How to write the image prompt (`still_prompt`) for one beat of a Short or explainer. The script AI follows this when it writes
each beat; people writing their own prompts can use it too.

## Narration is not a prompt

Narration is written for a listener: "the plane descended rapidly". An image model needs an instruction for a camera:
what is in frame, what it is doing, where the camera is, and how it is lit. If the prompt leaves something out, the image model
fills it in with its default, and the default is usually wrong. For an airliner the default is a calm side or rear view in
level flight with the landing gear down, which is how "descending steeply through clouds" became a plane that looks like it
is climbing away.

So every image prompt states all six slots explicitly, in this order.

## The six-slot formula

1. **Subject**: what is in frame, concretely. Type, shape, colours, how many. A real aircraft type is fine ("Boeing 737-800");
   never an airline name, logo, livery lettering, registration, flag or readable sign.
2. **Action / attitude**: what it is doing, in physical terms. For an aircraft: nose angle, climbing/level/descending, bank,
   gear up or down. For people: posture and what they are doing.
3. **Camera**: position, angle and shot size ("side view from slightly above", "low angle wide shot", "over-the-shoulder close-up").
   **When the beat describes a direction of motion, choose the camera angle where that direction is visible.** A dive or a
   descent needs a side view (slightly above): from below or behind, a diving plane and a climbing plane look the same. A climb
   also needs a side view. Level flight can use any angle (below, behind, three-quarter).
4. **Setting**: where and when (place, sky, weather, time of day).
5. **Mood / lighting**: the light that carries the emotion ("cold blue emergency lighting", "harsh floodlights", "backlit silhouette").
6. **Style**: shot-specific look only ("motion blur on wingtips", "shallow depth of field"). The general look is added by the
   pipeline automatically.

**Never name a part that should be absent.** "Landing gear retracted" makes the image model draw landing gear. Describe what IS
there ("clean smooth underside") and leave the rest to the negative prompt: for a plane in the air the pipeline adds
`landing gear, wheels, undercarriage` to the negative prompt automatically.

Length: 45-75 words, one sentence of comma-separated phrases. Vertical framing for Shorts (the pipeline sets the resolution).

Added automatically by the pipeline (do not write these):
- Style ending: `cinematic photorealistic, natural dramatic lighting, 35mm film look, highly detailed, no text, no watermark`
- Negative prompt: `text, watermark, logo, airline markings, registration numbers, deformed people, extra limbs, distorted faces, low quality, blurry, cartoon, anime`
  (+ `landing gear, wheels, undercarriage` when the beat is in the air)

## Bad vs good

Narration: "The jet then descended from sixteen thousand feet to three thousand in about two minutes."

- Bad: `A jet descending steeply through clouds, tense mood.`
  (No camera, no nose angle, no light: the model guesses all three, and its default is a calm level or climbing shot.)
- Good: `A Boeing 737-800 airliner in a steep nose-down emergency dive, nose pitched down about 25 degrees toward the ground, clean
  smooth underside, side view from slightly above so the downward angle is clear, dark storm clouds over desert at dusk, cold blue
  emergency lighting and red wingtip strobes, motion blur on the wingtips`

## Keywords

- **Camera**: low angle, high angle, eye level, over-the-shoulder, drone shot, aerial view, wide shot, medium shot, close-up,
  extreme close-up, viewed from below, viewed from behind, side view, from the cockpit seat
- **Motion** (for the animation prompt): dolly, tracking shot, handheld, slow motion, push in, pull back, parallax, slow pan
- **Attitude (aircraft)**: nose-down dive, steep descent, climbing, banking left/right, level flight, gear up, gear retracted,
  gear deployed, pitched up, pitched down, on final approach, wheels touching the runway, parked
- **Lighting**: golden hour, blue hour, dusk, night, emergency lighting, red warning lights, backlit, high contrast, silhouette,
  floodlit, overcast, harsh midday sun
- **Quality**: cinematic, photorealistic, 35mm film, shallow depth of field, motion blur, bokeh, film grain
- **Never ask for**: text, letters, numbers, logos, brand or airline names, livery lettering, flags, registrations, signs,
  real people's faces (show people from behind, in silhouette or at a distance)

## Worked examples

**1. Aircraft in descent**
Narration: "Minutes later the airliner plunged eleven thousand feet as alarms sounded on board."
Prompt: `A white twin-engine narrow-body airliner with a plain grey tail in a steep nose-down descent, nose pitched down sharply
toward the desert, clean smooth underside, slight right bank, side view from slightly above so the downward angle is clear, torn
grey clouds over brown desert at dusk, harsh backlight with red wingtip strobes, motion blur on the wingtips and engine exhaust`

**2. Cockpit interior**
Narration: "Inside the cockpit, the two pilots were fighting over the controls."
Prompt: `Two pilots in white shirts struggling over the control yokes of an airliner cockpit, one leaning across the other,
seen from behind the seats at shoulder height, faces turned away, dark sky through the windscreen, red master-warning lights
and dim instrument glow, shallow depth of field, slight motion blur on their arms`

**3. Government building**
Narration: "The ministry said it was treating the incident as a terrorist act."
Prompt: `A large pale stone government building with tall columns and wide steps, empty plaza in front, low angle wide shot from
the bottom of the steps, overcast late afternoon sky, flat cold light with long shadows, sober serious mood, sharp architectural
detail`

**4. Newsroom**
Narration: "Newsrooms across the region were racing to confirm what had happened."
Prompt: `A busy television newsroom at night, journalists seen from behind at desks facing a wall of glowing monitors showing
blurred abstract images, medium wide shot from the back of the room, dark room lit by cold blue screen light, tense focused mood,
shallow depth of field, no readable screens`

**5. Airport at night**
Narration: "The jet finally came to a stop at a remote airport in the north of the country."
Prompt: `A white airliner parked on a dark apron at a small desert airport, gear down, engines off, emergency vehicles with flashing
lights around it, wide shot from a low angle across the tarmac, night, harsh orange floodlights and red and blue reflections on the
wet concrete, tense quiet mood`

**6. Politician at podium**
Narration: "The prime minister told reporters the country would not let the matter go."
Prompt: `A man in a dark suit speaking at a wooden podium with microphones, seen from behind and slightly to the side so his face is
not visible, rows of photographers in front of him, medium wide shot, bright camera flashes against a dark blue backdrop,
serious tense mood, shallow depth of field`

**7. Cabin passengers**
Narration: "Passengers said they were certain they were going to die."
Prompt: `Rows of frightened airline passengers gripping their armrests and bracing forward, oxygen masks dangling from the ceiling,
seen from the aisle behind them at seat height, faces turned away or in shadow, dim cabin with red emergency lighting, chaotic
tense mood, slight camera shake and motion blur`

**8. Radar screen**
Narration: "Air traffic controllers watched the flight's signal drop on their screens."
Prompt: `A dark air-traffic-control radar screen with a green sweeping line and a few glowing abstract blips, one blip trailing
downward, close-up at a slight angle, a controller's silhouetted shoulder in the foreground, dark control room lit only by green
screen glow, tense mood, shallow depth of field, no readable numbers or text`

**9. Distant city skyline**
Narration: "Back in the capital, officials met late into the night."
Prompt: `A distant city skyline of tall office towers at night, scattered lit windows, seen from across a wide river, wide shot from
a low vantage point on the far bank, deep blue hour sky with faint clouds, cold city lights reflected in the water, quiet tense
mood, long exposure smooth water`

**10. Aircraft after landing**
Narration: "After the emergency landing, passengers were kept on board for hours."
Prompt: `A white narrow-body airliner standing still on a sunlit desert airport apron, gear down, doors closed, stairs not attached,
two police cars and a fire truck parked nearby, wide shot from ground level at a three-quarter front angle, harsh midday sun and heat
haze, empty tense waiting mood`
