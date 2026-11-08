# Licence notice for the HaGRID demo media

The files in this folder (`hagrid-demo.gif`, `hagrid-demo.mp4`,
`dashboard-dark.png`, `dashboard-light.png` and `diagnostics-dark.png`) are
**not** covered by this repository's MIT licence.

They are adapted from images in **HaGRID — HAnd Gesture Recognition Image
Dataset** by Alexander Kapitanov, Andrey Makhlyarchuk, Karina Kvanchiani and
co-authors: <https://github.com/hukenovs/hagrid>.

- **Licence:** the HaGRID "Public license with attribution and conditions
  reserved", a variant of CC BY-SA 4.0:
  <https://github.com/hukenovs/hagrid/blob/master/license/en_us.pdf>.
  These adapted files are made available under the same licence.
- **Source used:** the downscaled 384p sample
  [`cj-mills/hagrid-sample-30k-384p`](https://huggingface.co/datasets/cj-mills/hagrid-sample-30k-384p).
- **Changes made:** images were further resized and letterboxed; faces were
  automatically blurred; some images had photometric changes applied
  (darkening with noise, overexposure, warm colour cast, lighting gradient) to
  simulate lighting conditions; HandWave's hand landmarks and an information
  panel were drawn on top. The dashboard screenshots show a cropped photo
  inside HandWave's window.
- **No endorsement:** HaGRID's authors do not endorse HandWave.
- **Disclaimer:** the material is provided "as is", without warranties, as set
  out in Section 5 of the HaGRID licence.
- **Personal rights:** the HaGRID licence does not grant publicity or privacy
  rights of the people pictured (Section 2(b)(1)). Faces are blurred to reduce
  this risk. If you are pictured and want an image removed, open an issue and
  it will be taken down.

Regenerate with `python -m benchmarks.make_hagrid_demo --data-dir <HaGRID sample>` and
`python scripts/capture_docs_screenshots.py --hagrid-dir <HaGRID sample>`.
