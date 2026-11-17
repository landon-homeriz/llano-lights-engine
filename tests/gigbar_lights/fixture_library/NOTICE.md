# Test fixtures from the open fixture libraries

- `ofl/chauvet-dj/gigbar-2.json`, `ofl/venue/tetra-bar.json` (OFL's own manufacturer/fixture layout): Open Fixture Library
  (https://github.com/OpenLightingProject/open-fixture-library, `fixtures/chauvet-dj/gigbar-2.json`
  and `fixtures/venue/tetra-bar.json`, commit 2fc6128964335bcac14d6429eea5e1eb690db5d8), MIT License
  (`ofl/LICENSE-MIT.txt`), copied unmodified.
- `qlcplus/Chauvet-GigBAR-2.qxf`: QLC+ (https://github.com/mcallegari/qlcplus,
  `resources/fixtures/Chauvet/Chauvet-GigBAR-2.qxf`, commit 752c96285cac97acb782b9d298d9667c4e62c689),
  Apache License 2.0 (`tools/gigbar_lights/fixtures/qlcplus/LICENSE-APACHE-2.0.txt`), copied unmodified.

The GigBAR 2 is in both libraries, so the tests read it from each and check they drive the same bytes.
