# Native Community document interchange fixture

This is synthetic test content. `original.txt` is the semantic source document,
with a form-feed separating two multicolumn pages. It has no geometric coordinate
system. Each generated PNG is an immutable original page raster, also used as
the rendered annotation image; its raster-to-render matrix is identity.
`manifest.json` records separate source-document, original-page and render
digests, image dimensions, page IDs and the coordinate convention. The same
digests and page/document IDs are carried in native task data.

Native rectangles use percentages of the exact 1200×1600 raster, with the origin
at the top left and rotation zero. Convert to pixels with x/100×1200 and
y/100×1600. `config.xml` uses stock Image, RectangleLabels, per-region TextArea,
Choices and Relations tags. `result.json` has typed regions, corrected Unicode
transcription, page/document classifications and a `precedes` reading-order
relation. There is one native task per page. This supplies no PDF text layer,
document-wide editor, canonical revision registry or publication semantics.

Regenerate using the candidate image's pinned Pillow/runtime:

```sh
docker run --rm -v "$PWD/fixtures/oidc:/fixtures" --entrypoint python label-studio-oidc:candidate /fixtures/generate.py
```

The qualification driver loads the corpus under two actual Keycloak identities,
checks native author/update-actor fields, edits transcription in the stock
editor, exports again and verifies relations, coordinates and Unicode.
`deploy/oidc/evidence/native-export.json` is native API-created baseline evidence;
`editor-export.json` records native UI edits; `service-import.json` separately
identifies the authenticated import service and native attribution.
Task responses may expand `completed_by` into a user object; JSON exports use
its native ID. Consumers must preserve that ID and their issuer/subject binding,
and distinguish original author, update actor and imported attribution.
