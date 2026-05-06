# Stack-managed custom formats

These JSON files are pushed to Sonarr/Radarr by the orchestrator at startup
(see `core/custom_formats.py`). Recyclarr does NOT manage them — it only
manages formats listed by `trash_ids` in `recyclarr.yml`.

## Score policy

Applied to the `Multi-Audio Preferred` quality profile:

| Format | Score |
| --- | --- |
| Dual Audio (ITA + Original) | +500 |
| Italian Only | +50 |

Net effect: a dual-audio release outranks any single-language release at
the same quality tier. A single-language Italian release is acceptable as a
fallback while the catch-up worker searches for an upgrade.
