# Fayetteville MTB Trails

A small, dependency-free web app that lists mountain bike trails in and around
**Fayetteville, Arkansas**, lets you **sort and filter by difficulty**, and
shows every trail on an **interactive map**.

## Features

- **Sort by difficulty** (easy → hard or hard → easy), length, or name.
- **Filter by difficulty** with color-coded toggles using the standard IMBA
  rating scale:
  - 🟢 Green — Easy
  - 🔵 Blue — Intermediate
  - ⚫ Black — Advanced
  - 🟣 Double Black — Expert
- **Interactive map** (Leaflet + OpenStreetMap, no API key needed). Click a
  trail card to zoom the map, or click a map marker to highlight the card.
- Length, descent, and feature tags for each trail.

## Run it

It's a static site — no build step. Either open `index.html` directly in a
browser, or serve the folder:

```bash
cd mtb-trails
python3 -m http.server 8000
# then visit http://localhost:8000
```

> The map tiles and Leaflet library load from public CDNs, so an internet
> connection is required.

## Trail data

Trails live in [`trails.js`](./trails.js). Add or edit entries there — each
trail has a name, system, difficulty, length, descent, coordinates,
description, and feature tags. Coordinates are approximate trailhead locations
for orientation only; verify on [Trailforks](https://www.trailforks.com/region/fayetteville/)
or [MTB Project](https://www.mtbproject.com/directory/8009548/fayetteville-ar)
before riding.

## Files

| File         | Purpose                                  |
| ------------ | ---------------------------------------- |
| `index.html` | Page structure and CDN includes          |
| `styles.css` | Styling                                  |
| `trails.js`  | Trail data + difficulty metadata         |
| `app.js`     | Map, sorting, filtering, and rendering    |
