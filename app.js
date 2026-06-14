/* global L, TRAILS, DIFFICULTY */

const state = {
  sort: 'difficulty-asc',
  active: new Set(Object.keys(DIFFICULTY)),
  selectedId: null,
};

const markers = {};
let map;

function initMap() {
  map = L.map('map').setView([36.06, -94.17], 12);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map);

  TRAILS.forEach((trail) => {
    const meta = DIFFICULTY[trail.difficulty];
    const marker = L.circleMarker([trail.lat, trail.lng], {
      radius: 8,
      color: '#ffffff',
      weight: 2,
      fillColor: meta.color,
      fillOpacity: 0.95,
    }).addTo(map);

    marker.bindPopup(popupHtml(trail));
    marker.on('click', () => selectTrail(trail.id, { fromMap: true }));
    markers[trail.id] = marker;
  });
}

function popupHtml(trail) {
  const meta = DIFFICULTY[trail.difficulty];
  return `
    <div>
      <span class="pop-badge" style="background:${meta.color}">${meta.short} · ${meta.label}</span>
      <h3>${trail.name}</h3>
      <p class="pop-sys">${trail.system}</p>
      <p style="margin:0;font-size:0.82rem">
        ${trail.lengthMi} mi · ${trail.descentFt} ft descent
      </p>
    </div>`;
}

function visibleTrails() {
  const filtered = TRAILS.filter((t) => state.active.has(t.difficulty));

  const sorters = {
    'difficulty-asc': (a, b) =>
      DIFFICULTY[a.difficulty].order - DIFFICULTY[b.difficulty].order,
    'difficulty-desc': (a, b) =>
      DIFFICULTY[b.difficulty].order - DIFFICULTY[a.difficulty].order,
    'length-asc': (a, b) => a.lengthMi - b.lengthMi,
    'length-desc': (a, b) => b.lengthMi - a.lengthMi,
    'name-asc': (a, b) => a.name.localeCompare(b.name),
  };

  return filtered.sort(sorters[state.sort] || sorters['difficulty-asc']);
}

function render() {
  const list = document.getElementById('trail-list');
  const trails = visibleTrails();

  document.getElementById('list-count').textContent =
    `${trails.length} trail${trails.length === 1 ? '' : 's'} shown`;

  list.innerHTML = '';

  if (trails.length === 0) {
    list.innerHTML =
      '<p class="list-count">No trails match the selected difficulties.</p>';
  }

  trails.forEach((trail) => {
    const meta = DIFFICULTY[trail.difficulty];
    const card = document.createElement('div');
    card.className =
      'trail-card' + (trail.id === state.selectedId ? ' selected' : '');
    card.style.borderLeftColor = meta.color;
    card.dataset.id = trail.id;

    card.innerHTML = `
      <div class="row1">
        <h3>${trail.name}</h3>
        <span class="badge" style="background:${meta.color}">${meta.short}</span>
      </div>
      <p class="system">${trail.system} · ${meta.label}</p>
      <div class="stats">
        <span><b>${trail.lengthMi}</b> mi</span>
        <span><b>${trail.descentFt}</b> ft descent</span>
      </div>
      <p class="desc">${trail.description}</p>
      <div class="tags">
        ${trail.features.map((f) => `<span class="tag">${f}</span>`).join('')}
      </div>`;

    card.addEventListener('click', () => selectTrail(trail.id));
    list.appendChild(card);
  });

  TRAILS.forEach((trail) => {
    const marker = markers[trail.id];
    if (!marker) return;
    const shouldShow = state.active.has(trail.difficulty);
    if (shouldShow && !map.hasLayer(marker)) marker.addTo(map);
    if (!shouldShow && map.hasLayer(marker)) map.removeLayer(marker);
  });
}

function selectTrail(id, opts = {}) {
  state.selectedId = id;
  render();

  const card = document.querySelector(`.trail-card[data-id="${id}"]`);
  if (card && !opts.fromMap) {
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  const marker = markers[id];
  const trail = TRAILS.find((t) => t.id === id);
  if (marker && trail) {
    map.setView([trail.lat, trail.lng], Math.max(map.getZoom(), 14), {
      animate: true,
    });
    marker.openPopup();
  }
}

function buildFilterPills() {
  const container = document.getElementById('filter-pills');
  Object.entries(DIFFICULTY).forEach(([key, meta]) => {
    const pill = document.createElement('button');
    pill.className = 'pill active';
    pill.dataset.key = key;
    pill.innerHTML = `<span class="dot" style="background:${meta.color}"></span>${meta.short}`;
    pill.addEventListener('click', () => {
      if (state.active.has(key)) {
        state.active.delete(key);
        pill.classList.remove('active');
        pill.classList.add('inactive');
      } else {
        state.active.add(key);
        pill.classList.add('active');
        pill.classList.remove('inactive');
      }
      render();
    });
    container.appendChild(pill);
  });
}

function wireControls() {
  document.getElementById('sort').addEventListener('change', (e) => {
    state.sort = e.target.value;
    render();
  });

  document.getElementById('show-all').addEventListener('click', () => {
    state.active = new Set(Object.keys(DIFFICULTY));
    document.querySelectorAll('.pill').forEach((p) => {
      p.classList.add('active');
      p.classList.remove('inactive');
    });
    render();
  });
}

window.addEventListener('DOMContentLoaded', () => {
  initMap();
  buildFilterPills();
  wireControls();
  render();
});
