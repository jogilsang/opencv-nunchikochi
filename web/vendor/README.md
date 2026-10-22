# web/vendor — third-party, pinned

Vendored (no CDN) so the web client has no network dependency at runtime.

| file | source | version | license | bytes |
|---|---|---|---|---|
| `three.module.min.js` | three.js (mrdoob/three.js) | r158 (`0.158.0`) | MIT (`three.LICENSE`) | 652,433 |

- `three.module.min.js` is the official minified **single-file ES module** build. It is
  self-contained (no sub-imports), so `import * as THREE from "./vendor/three.module.min.js"`
  works with the app's existing module scripts and needs no bundler.
- Bundle size 652 KB < 700 KB target. We render only a sphere head + capsule body + simple
  eyes/mouth and implement drag rotation by hand (no `OrbitControls`), so nothing else from
  three.js is pulled in beyond the core that ships in this one file.
- To update: re-pin a tagged release, refresh `three.LICENSE` from the matching tag, and
  update the table above. Do not load three.js from a CDN.
