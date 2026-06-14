/*
 * Mountain bike trails in and around Fayetteville, Arkansas.
 *
 * Difficulty ratings follow the standard IMBA trail rating scale:
 *   green        -> Easy / Beginner
 *   blue         -> Intermediate
 *   black        -> Advanced
 *   double-black -> Expert / Pro
 *
 * Coordinates are approximate trailhead locations and are intended for
 * orientation on the map, not turn-by-turn navigation. Always check a
 * local source (Trailforks, MTB Project, or park signage) before riding.
 */

const TRAILS = [
  {
    id: 'cp-the-grind',
    name: 'The Grind',
    system: 'Centennial Park at Millsap Mountain',
    difficulty: 'green',
    lengthMi: 2.4,
    descentFt: 180,
    lat: 36.0492,
    lng: -94.2185,
    description:
      'A smooth, flowing beginner loop at Centennial Park. Wide tread and gentle grades make it the perfect first dirt ride or warm-up lap.',
    features: ['Flow', 'Beginner friendly', 'Wide tread'],
  },
  {
    id: 'cp-jurassic',
    name: 'Jurassic',
    system: 'Centennial Park at Millsap Mountain',
    difficulty: 'blue',
    lengthMi: 1.8,
    descentFt: 260,
    lat: 36.0508,
    lng: -94.2201,
    description:
      'Rolling intermediate flow trail with bermed corners and small rollers. A favorite for building speed and confidence.',
    features: ['Berms', 'Rollers', 'Flow'],
  },
  {
    id: 'cp-fire-line',
    name: 'Fire Line',
    system: 'Centennial Park at Millsap Mountain',
    difficulty: 'black',
    lengthMi: 1.1,
    descentFt: 340,
    lat: 36.0521,
    lng: -94.2178,
    description:
      'Steep, technical descent with rock features and optional drops. Advanced riders only — scout the features first.',
    features: ['Rock features', 'Drops', 'Steep'],
  },
  {
    id: 'cp-pro-line',
    name: 'Centennial Pro Line',
    system: 'Centennial Park at Millsap Mountain',
    difficulty: 'double-black',
    lengthMi: 0.6,
    descentFt: 290,
    lat: 36.0533,
    lng: -94.2169,
    description:
      'Expert-only gravity line with large jumps, gap features, and big drops. Built for skilled riders comfortable in the air.',
    features: ['Large jumps', 'Gaps', 'Big drops'],
  },
  {
    id: 'kessler-summit',
    name: 'Kessler Summit Loop',
    system: 'Mount Kessler Regional Park',
    difficulty: 'blue',
    lengthMi: 4.2,
    descentFt: 520,
    lat: 36.0312,
    lng: -94.1976,
    description:
      'Classic Ozark singletrack climbing toward the Mount Kessler ridge with rewarding views and a fast, rooty return.',
    features: ['Climbing', 'Roots', 'Views'],
  },
  {
    id: 'kessler-fossil',
    name: 'Fossil Flats',
    system: 'Mount Kessler Regional Park',
    difficulty: 'green',
    lengthMi: 2.0,
    descentFt: 120,
    lat: 36.0298,
    lng: -94.1991,
    description:
      'Mellow lower-mountain loop with crushed limestone and minimal climbing. Great for families and new riders.',
    features: ['Easy grade', 'Family friendly', 'Crushed stone'],
  },
  {
    id: 'kessler-back40-connector',
    name: 'Kessler Tech Connector',
    system: 'Mount Kessler Regional Park',
    difficulty: 'black',
    lengthMi: 1.5,
    descentFt: 410,
    lat: 36.0331,
    lng: -94.1962,
    description:
      'Rocky, root-laden advanced segment with tight switchbacks and exposed ledges. Rewards good line choice and bike handling.',
    features: ['Switchbacks', 'Rock ledges', 'Roots'],
  },
  {
    id: 'lake-fayetteville-loop',
    name: 'Lake Fayetteville Singletrack',
    system: 'Lake Fayetteville Trails',
    difficulty: 'green',
    lengthMi: 5.5,
    descentFt: 230,
    lat: 36.1407,
    lng: -94.1419,
    description:
      'A long, scenic lakeside loop of beginner-friendly singletrack. Mostly flat with a few short punchy climbs around the shoreline.',
    features: ['Lakeside', 'Long loop', 'Beginner friendly'],
  },
  {
    id: 'lake-fayetteville-north',
    name: 'North Shore Rollers',
    system: 'Lake Fayetteville Trails',
    difficulty: 'blue',
    lengthMi: 3.1,
    descentFt: 300,
    lat: 36.1471,
    lng: -94.1456,
    description:
      'The more playful north-side section with rolling terrain, small wooden features, and faster flow than the main loop.',
    features: ['Wood features', 'Flow', 'Rollers'],
  },
  {
    id: 'sequoyah-woods',
    name: 'Mount Sequoyah Woods',
    system: 'Mount Sequoyah Woods',
    difficulty: 'blue',
    lengthMi: 2.7,
    descentFt: 380,
    lat: 36.0703,
    lng: -94.1432,
    description:
      'Tight, twisty intermediate trails packed into a compact urban forest east of downtown. Punchy climbs and quick descents.',
    features: ['Twisty', 'Urban forest', 'Punchy climbs'],
  },
  {
    id: 'markham-hill',
    name: 'Markham Hill Trails',
    system: 'Markham Hill',
    difficulty: 'green',
    lengthMi: 1.9,
    descentFt: 160,
    lat: 36.0561,
    lng: -94.1798,
    description:
      'Quiet, easy natural-surface trails on a wooded hillside close to the University of Arkansas campus.',
    features: ['Quiet', 'Natural surface', 'Beginner friendly'],
  },
  {
    id: 'kessler-rock-garden',
    name: 'Kessler Rock Garden',
    system: 'Mount Kessler Regional Park',
    difficulty: 'double-black',
    lengthMi: 0.8,
    descentFt: 360,
    lat: 36.0344,
    lng: -94.1949,
    description:
      'A notorious expert-only chute of stacked rock gardens and steep, committing moves. The toughest natural tech on the mountain.',
    features: ['Rock gardens', 'Steep', 'Committing moves'],
  },
];

// Difficulty metadata used across the UI (ordering, labels, colors).
const DIFFICULTY = {
  green: { order: 1, label: 'Easy', short: 'Green', color: '#2e9e44' },
  blue: { order: 2, label: 'Intermediate', short: 'Blue', color: '#2670d8' },
  black: { order: 3, label: 'Advanced', short: 'Black', color: '#222222' },
  'double-black': {
    order: 4,
    label: 'Expert',
    short: 'Double Black',
    color: '#7b2ff7',
  },
};
