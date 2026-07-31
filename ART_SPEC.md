# Poo — art spec (read before generating)

The single most important rule: **every image must be the same character, same
pose, same size, same camera distance — only the FACE changes.** If the body
shifts or resizes between images, swapping them looks like a glitchy slideshow.
That was the problem with the first build.

## Settings for every image

- Size: **1024 × 1024** (or larger)
- Background: **fully transparent PNG** — no white, no drop shadow, no floor
- One character alone — **no text, no labels, no grid, no multiple poses**
- Framing: full body, sitting, facing camera, centered, with a little empty
  space around her so nothing is cropped at the edges

## The prompt

Generate the first one, then for each following image say:
*"Same character, same pose, same size and framing, transparent background —
only change the facial expression to: ..."*

Base prompt:

> A cute fluffy lilac plush bunny-puppy character named Poo, sitting facing the
> camera, full body, big sparkly purple eyes, pink cheek blush, small heart
> pendant with "Poo" written on it, soft fur texture, kawaii plush toy style,
> soft studio lighting, transparent background, centered, full body visible with
> margin around it, 1024x1024

## The expressions to generate

Save each with **exactly** these filenames into `assets/poo/`:

| filename | expression |
|---|---|
| `hi_neutral.png` | calm, gentle, eyes open, small closed smile |
| `hi_blink.png` | identical to neutral but **eyes closed** (blinking) |
| `hi_happy.png` | warm smile, happy squinting eyes |
| `hi_excited.png` | big open-mouth smile, wide sparkling eyes, joyful |
| `hi_love.png` | eyes closed in happy arcs, blushing, in love |
| `hi_shy.png` | looking away bashfully, strong blush, paws near face |
| `hi_surprised.png` | wide startled eyes, small open mouth |
| `hi_sleepy.png` | droopy half-closed eyes, small yawn |

Optional extras if you want more depth later:
`hi_curious.png` (head tilt, questioning), `hi_giggle.png` (laughing).

## After you have them

Drop all the PNGs into `assets/poo/` (same folder as the current art) and tell
me. The app auto-detects any `hi_*.png` it finds and uses it — anything missing
just falls back to the closest expression, so partial sets still work.
