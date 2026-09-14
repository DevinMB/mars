# Brand assets

Source artwork. Not served by the console and not bundled into its image.

| File | What it is |
|---|---|
| `mars-logo.png` | The full logo: planet, ring, squirrel, dashboard, wordmark |
| `mars-icon.png` | The app icon version of the same illustration |
| `mars-wordmark.png` | The logo with its transparent margin trimmed |

Use these for documentation, a README header, a site — anywhere the image is shown
large enough to read.

**They are deliberately not used in the console.** At 16 to 32 pixels the
illustration collapses into noise. The console draws
`frontend/src/components/MarsMark.jsx` instead: the same identity reduced to three
shapes — planet, orbital ring, one data square — drawn at the size it is actually
used. `frontend/public/mark.svg` is the same mark as a standalone file, used as the
favicon, and every `icon-*.png` is generated from it so all sizes agree.

To regenerate the raster fallbacks after editing `mark.svg`:

```bash
docker run --rm -v "$PWD/frontend/public:/p" python:3.12-slim sh -c '
  apt-get update -qq && apt-get install -y -qq libcairo2
  pip install -q cairosvg pillow
  python3 -c "
import cairosvg, io
from PIL import Image
svg = open(\"/p/mark.svg\",\"rb\").read()
for s in (16,32,48,180,192,512):
    Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg, output_width=s, output_height=s))).save(f\"/p/icon-{s}.png\")
Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg, output_width=64, output_height=64))).save(\"/p/favicon.ico\", sizes=[(16,16),(32,32),(48,48)])
"'
```
