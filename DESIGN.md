# Mitigus XIV — Design system

Dark "crystal" theme, ice-cyan accent. Single-file mobile-first panel (no build,
vanilla CSS/JS, served by a Python stdlib server). Faceted, precise, calm.

## Color — strategy: Restrained
Tinted near-black neutrals + one ice-cyan accent, reserved for the live/active state
and the single hero moment. OKLCH; never #000/#fff; every neutral tinted toward the
blue hue (~240). Semantic colors used only for status.

- `--bg`        oklch(0.15 0.02 245)   page, deepest
- `--surface`   oklch(0.19 0.024 245)  toolbars, quiet panels
- `--card`      oklch(0.22 0.026 245)  content surface
- `--line`      oklch(0.30 0.03 245)   hairline borders (1px)
- `--txt`       oklch(0.96 0.01 230)   primary text
- `--muted`     oklch(0.72 0.02 235)   secondary text
- `--faint`     oklch(0.55 0.02 238)   captions
- `--accent`    oklch(0.82 0.12 210)   ice cyan — primary action, live state, hero
- `--accent2`   oklch(0.66 0.13 248)   deep blue — secondary glow only
- `--on`        oklch(0.80 0.14 165)   good / success
- `--warn`      oklch(0.84 0.13 80)    caution (jitter/retrans)
- `--bad`       oklch(0.70 0.17 22)    error / offline

## Typography
System sans, one family: -apple-system, "Segoe UI", system-ui, sans-serif. Tabular
nums on every metric. Fixed rem scale, ratio ~1.2. Hierarchy via weight (600 / 700 /
800) and size, not color. No display fonts.

## Surfaces / elevation
Two neutral layers (surface vs card). Hairline 1px tinted borders. NO nested cards.
Not everything is a card: the toggle and the hero are distinct shapes; utility info
is quiet (inline rows, lists), not boxed.

## Icons
One consistent set of minimalist line SVG: 1.5px stroke, `currentColor`, ~18px,
rounded caps. No emojis anywhere.

## Motion
150–250ms, ease-out (quart/expo). Motion conveys state only: toggle, the cut "flash",
the live dot pulse, the sparkline. No orchestrated page-load sequence.

## Hierarchy law (fixes "everything looks the same")
Three tiers, visually distinct:
1. PRIMARY — mitigation toggle + cut hero. Largest, the only places with accent
   fill/glow and faceted detail.
2. SECONDARY — network HUD + margin slider. Medium, quiet card surfaces, accent only
   in data (sparkline, slider).
3. UTILITY — connect-PS5 guide, system status, log. Collapsed, list-style, smallest,
   no accent fill.
Vary spacing and scale across tiers. Never repeat the same card three times.

## Hard bans (from impeccable, currently violated by the old panel)
- No gradient text (`background-clip:text`). The old hero cut used it — replace with
  a solid `--accent` + weight.
- No identical card grid. The old panel was all same-size cards — that is the exact
  "everything looks the same" complaint.
- No glassmorphism by default. No side-stripe borders. No em dashes in copy.
