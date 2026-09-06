# CETA native visual design

Recorded September 6, 2026. This document describes the authorized native desktop
design and its source assets. See `docs/operations/CONTINUITY_MAP.md` and
`evidence/CETA_EMBER_RELEASE_VALIDATION.json` for the later desktop 0.3.1 build
and installed-application checkpoint. Public release remains pending there;
this design record does not relabel earlier installers as containing the interface.

## User authority and reference

The user supplied the image at
`C:\Users\Quencher\Downloads\ChatGPT Image Sep 6, 2026, 10_12_25 AM.png` as the
visual reference for the native CETA application. Its SHA-256 is
`a5515b49fc7b4226fb2cb98674617c28121058b9f5a89e7d60a008e93b822ce3`.
The date in its filename is a source label, not a separately verified creation time.

The approved direction is black and charcoal surfaces, ember-orange accents,
white text, a volcanic orb mark, native line icons, an illustrated navigation
sidebar, a conversation rail, and readable message and editor controls. The
official product name remains **CETA**. This authorizes CETA's visual work within
its existing repository; it does not authorize importing another project's
branding, implementation, data, models, or evidence.

The user subsequently directed that each native section have a different
planetary landscape and space sky, rather than repeating volcanic scenery
throughout. The generated section images implement that distinction while
retaining the shared charcoal and ember control palette.

## Seven environments

These are descriptive names for fictional decorative artwork, not claims about
real astronomical locations. The images were generated for this CETA task and
are bundled visual assets, not model packs or user content.

| Section | Environment | Asset under `src/ceta_desktop/assets/` |
| --- | --- | --- |
| Chat | Ember world: volcanic plains and a glowing lava planet | `chat-landscape.png` |
| Projects | Ringed ice world: blue-lit rock spires under a ringed planet | `projects-landscape.png` |
| Library | Amber desert: eroded mesas beneath a golden planet and small moons | `library-landscape.png` |
| Models | Amethyst world: crystalline terrain, violet aurora, and a dark planet | `models-landscape.png` |
| Workloads | Binary-star canyon: dark red cliffs under two warm stars | `workloads-landscape.png` |
| Updates | Gas-giant shoreline: a dark ocean and cyan-lit giant planet | `updates-landscape.png` |
| Settings | Lunar Earthrise: quiet grey terrain beneath a blue world | `settings-landscape.png` |

`ember-landscape.png` is the earlier generated volcanic sidebar fallback. It is
retained as a separate asset; the seven section files provide the current scene
mapping. The CETA orb and line icons are painted natively by `theme.py` and do not
depend on downloaded graphics.

## Asset identity at this checkpoint

| Asset | SHA-256 |
| --- | --- |
| `chat-landscape.png` | `438fa90241592ab8765f78b51f087846f52e763c1245fc727d783f3b0760929a` |
| `projects-landscape.png` | `3e704e1b8adee30a788d972836522065b34f0eb87945e9719b44bd827a1cc91a` |
| `library-landscape.png` | `47065446c38ac5ae9e96129dc637d622bb13ceef40c1e60db67f3b05a4f22b30` |
| `models-landscape.png` | `bdca4711b8678933801076744e7132ac0ff54fb0192460206718722e7b19491c` |
| `workloads-landscape.png` | `49b81bfc25736333a072ea658750b7bb9ff10b8a9f03c737fae8e67fd65c3800` |
| `updates-landscape.png` | `39f88bc94005264d8f7b3fee66b183e41d48f6b5387139cdf66164ec02abcfbf` |
| `settings-landscape.png` | `89e0890b4cef22ada2b0199cbad032f1e746ca3a5c96fa985ab7d2dff9953851` |
| `ember-landscape.png` | `eefea3705eaa88688c5f99d6ebe8775036364b24c7b1cdadbc4036ed157f1bb6` |

## Readable native behavior

`ScenePage` selects the section's local artwork and shades it behind content.
`EmberSidebar.set_scene()` follows navigation with a subtle lower illustration.
Images cover their containers and crop with resizing; dark gradients protect
text contrast. Missing optional images fall back to dark gradients so browsing,
editing, and other available controls continue to work.

Artwork should remain visible around and between charcoal cards. Navigation
selection uses orange text and a left accent stripe; keyboard focus has a visible
orange boundary. Text, buttons, fields, menus, and dialogs remain native Qt
controls. Controls must remain usable with keyboard navigation, long text, small
windows, and Windows display scaling. Visual QA must inspect those conditions
and ensure that an opaque child panel does not accidentally cover its scene.

Conversation bubbles display saved or currently streaming messages. Fenced code
blocks provide explicit copying. The design must not seed fictional conversations,
invent model availability, show fabricated workload success, or present sample
content as a user's history. Empty states explain the next actual action. A
decorative landscape, status badge, or screenshot is not execution evidence.

## Release boundary

The redesign preserves explicit file saves, user-directed attachment and command
execution, local-service privacy boundaries, optional model downloads, signed
update verification, and personal publisher verification. The visual treatment
does not establish Windows CA trust; the selected personal signature remains
separate from Authenticode.

Before publication, include these assets in the built payload, validate every
native section and its real controls, build a new installer, and verify that
installer's exact bytes and personal receipt. Update release screenshots from
that application rather than treating the supplied design image as a screenshot
of a functioning release. Preserve earlier candidates and their historical
evidence with their original hashes and validation scope.
