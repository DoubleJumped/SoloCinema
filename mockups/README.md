# SoloCinema — Design Directions

Static self-contained mockups for SoloCinema (no app wiring — sample Regina screening
data is inlined in each file).

**Current state:** the split-flap departures board (`designs/02-departures.html`) was
chosen as the base design. The carousel now shows that base plus four re-skin variants
of it. The four other original concept designs remain on disk (see below) but are no
longer in the carousel.

## The board family (in the carousel)

| # | Variant | Direction |
|---|---------|-----------|
| 1 | The Departures Board — Base | The chosen base. Time-sorted board (TIME · DATE · FILM · THEATRE · SEATS TAKEN), full filter rail (Tonight/Tomorrow + date dropdown, chains, film dropdown, Under-5-Seats-Sold toggle), seats digits colored green &lt;5 / amber 5–19 / red 20+, flap-tile logo that flips on load/click/ambiently. |
| 2 | Sodium Glow (`board-a-sodium.html`) | All-warm umber monochrome hall; ivory flaps, amber afterglow, heavier slower flips (17s ambient). |
| 3 | Ivory Hall (`board-b-ivory.html`) | Daylit station: light plaster page and controls; the board and logo stay dark physical objects. |
| 4 | Cool Cathode (`board-c-cathode.html`) | Ice-blue slate + cyan accent, sharper tiles, snappy sub-second flips (9s ambient); 5–19 tier stays warm for signal clarity. |
| 5 | The Marquee (`board-d-marquee.html`) | Burgundy + gold movie-palace lobby, chasing bulb strip on the sign, flaps settle with a tiny pop. |

## Run it

```sh
cd mockups
python3 -m http.server 8888
# open http://localhost:8888
```

Or just open `mockups/index.html` directly in a browser — everything works from `file://`.
Google Fonts are loaded from the network; everything else is inline.

Cycle designs with **← / →**, jump with **1–5**, **Replay** reloads the current design's
load animation, **Open ↗** shows it standalone.

## The five original concept directions (on disk, not in the carousel)

| # | Design | Direction |
|---|--------|-----------|
| 1 | The Private Screening | Movie-palace luxe: warm black, velvet, brass; each card renders the actual seat map as a dot matrix of dark, empty seats. |
| 2 | The Departures Board | A split-flap (Solari) board, time-sorted. Full filter rail (Tonight/Tomorrow + date dropdown, chains, film dropdown, Under-5 toggle), flap-tile logo, and signal lamps: green < 5, amber 5–19, red 20+, unlit = no data. |
| 3 | Dusk | Saskatchewan "living skies" drive-in: dusk-gradient hero, a horizon line as the page's structural device, sun-height occupancy meters. |
| 4 | The Auditorium *(experimental)* | The seat map IS the interface: the page is a dark auditorium; every seat is a screening, and the glowing screen shows whichever one you select. Keyboard-navigable. |
| 5 | The Reel *(experimental)* | A 35mm film strip on an editor's light table: scrub horizontally through frames; emptiness is exposure — an empty theatre is a luminous, unexposed frame. |

All five use the same inlined sample dataset and are responsive to 360px, honor
`prefers-reduced-motion`, and have visible keyboard focus states.
