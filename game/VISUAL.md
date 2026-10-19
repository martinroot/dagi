# Vector Character Studio (v7)

The character, material objects, landscape and authored graphics use the same
Canvas2D vector renderer and lighting palette. There are no raster backgrounds,
sprites, downloaded artwork or image-generation calls in the game runtime.

New physical sessions start with an articulated anatomical skeleton: a skull,
spine, ribs, clavicles, pelvis, paired forearm/shin bones, hands and feet. The
colliding rig has separate shoulder/hip attachments on its rigid torso. Ribs and
small finger marks describe its surface; they are not independently actuated
rigid bodies. It is a stylized 2D anatomical rig, not a medical biomechanics model.
The initial body still falls without a learned controller.

## Authoring through the agent

Read `game_observe {"view":"schema","path":"visual"}` once for the exact contract.
Read `game_observe {"view":"visual"}` for current proportions, surface, light,
atmosphere and layer metadata. Read a layer's commands with `path:layer_id` and
optional command-index `offset`; results are paged in groups of 12. The self
passport carries layer counts rather than copying every curve on every API call.

Submit `character` and `art` edits with the usual `game_iteration`. They participate
in the same draft, baseline/candidate physical trials, source hash, countdown,
atomic publication and rollback as existing project and mechanism edits.

```json
{
  "objective": "Change my silhouette and use warm directional lighting",
  "changes": [
    {"operation":"character","values":{
      "name":"Aster", "style":"anatomical", "shoulder_width":32,
      "bones":{"right_elbow":{"length":38,"radius":7,"mass":1.1}},
      "surface":{"skin":"#c99b7d","muscle":"#a56c59","accent":"#357e80",
                 "muscles":0.9,"roughness":0.6,"crest":0.4}
    }},
    {"operation":"art","values":{
      "mode":"soft", "ambient":0.5,
      "key":{"x":170,"y":80,"color":"#fff0d3","intensity":1.1},
      "atmosphere":{"depth":0.8,"haze":0.25,"wind":0.2}
    }}
  ]
}
```

This example is syntax, not an installed episode or ability. Length, collision
radius and mass change actual inertia and contacts. Muscle volume shapes the
surface inside each capsule envelope. Appearance-only changes preserve the live
solver and momentum. Geometry publication remaps the latest live pose, keeps the
hip in place and raises the envelope only if necessary to clear the floor; it
does not reset a fallen body into a standing pose. Changed proportions may require
new controllers. Extra physical limbs remain available through `appendage` edits.

`style` (`skeleton`, `anatomical`, `ceramic`, `ink`) supplies a rendering technique;
proportions and material parameters remain independent. A project can also use
`hide_body` and draw a fully custom character from the actual joint positions.
Soft gradients, stepped toon shading and noir coloration share the same geometry.
Ground shadows are approximate 2D light projections. Surface metallic/roughness,
rim highlights, muscle fibers and material grain are procedural vector effects,
not a physically based 3D ray tracer.

## Editable scene layers

`art.layers` contains up to twelve named layers, 240 commands total, 48 KB. Depth
orders them before/after the body; parallax separates distant scenery from nearby
geometry. Layer coordinates are world coordinates. Use project `draw` for live
animation driven by `t`, physical sensors and events. Both use the same primitive
contract: line, circle, ellipse, rectangle, text, polyline and Bezier paths.
Paints accept solid colors or ordered linear/radial gradient stops. Matrix
transforms, alpha, four blend modes and bounded shadows are available.

The procedural sky, atmospheric mountain strata, forest, clouds, ground and grass
share environment colors and the art light. Clouds and grass follow simulation
time, so pausing physics pauses their wind animation. Set atmosphere depth or
vegetation to zero to remove generated scenery; supply explicit mountain paths
for custom geometry. Painted terrain does not support a body: add static physical
polygons when collision is intended. No mandatory scenery props are installed.

The viewer reuses unchanged vector layer renderings at its actual backing
resolution, and rebuilds them when geometry, light, camera or resolution changes.
These are disposable caches of the editable vector source. No external image is
used. Auto detail reduces backing resolution on slow devices without changing the
physical clock or requesting a model call. High detail and economy can be selected
manually. Body/face camera buttons only change the viewer's framing.

## Verification and limits

Tests check collision geometry, actual shoulder/hip anchors, inertia, fallen-pose
publication, momentum preservation under cosmetic edits, legacy migration, curve
and gradient validation, vector layer ordering and bounded output. Browser QA
checks real publication, animation, style/light changes, mobile layout and an
untainted canvas usable by model vision. The QA provider is scripted, makes no
external LLM call and explicitly identifies its fixed torso support. Such a
fixture validates rendering/integration, not spontaneous invention, learned
standing, walking, or aesthetic quality. Judge visual quality from the screenshots
and motion recording, and iterate on it with the actual configured model.

Browser QA on the software-rendered Chromium fixture measured 59.98 physical Hz
and a settled frame interval of 16.67 ms (60 FPS) at automatic 1× backing detail;
recording also kept a 16.7 ms p95 frame interval. This is one test environment,
not a guarantee of 60 FPS at high detail on every device. No external image
requests, JavaScript errors or mobile page overflow were observed.
