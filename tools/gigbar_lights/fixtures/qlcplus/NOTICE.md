# QLC+ fixture definitions

The `.qxf` files in this folder are copied unmodified from the QLC+ fixture library
(https://github.com/mcallegari/qlcplus, `resources/fixtures/`, commit
752c96285cac97acb782b9d298d9667c4e62c689), Copyright Massimo Callegari and the QLC+ contributors
named in each file's `<Creator><Author>`, licensed under the Apache License, Version 2.0
(`LICENSE-APACHE-2.0.txt` in this folder).

| File | QLC+ path |
|---|---|
| Chauvet-GigBAR-Move.qxf | resources/fixtures/Chauvet/Chauvet-GigBAR-Move.qxf |
| Venue-Tetra-6.qxf | resources/fixtures/Venue/Venue-Tetra-6.qxf |
| Chauvet-Freedom-Stick.qxf | resources/fixtures/Chauvet/Chauvet-Freedom-Stick.qxf |

What the app needs that a library file lacks (program channels held at zero, strobe floors, the
byte picked inside a band, D-Fi notes) lives in `../overrides.json`, never in these files, so a
newer copy of any file can be dropped in as is.

## The whole library (Llano BL #12524)

`../qlcplus-library.zip` holds every `.qxf` under QLC+ `resources/fixtures/` at the same commit
(752c96285cac97acb782b9d298d9667c4e62c689), unmodified, under the same Apache License 2.0 and the same
authors. It is the library a DJ searches on the app's Setup screen (fixture_library.py);
`../qlcplus-library.json` is its index, rebuilt with `python -m tools.gigbar_lights.fixture_library`.
The three files above are byte-identical to their copies in the zip (test_rig_setup.py).
