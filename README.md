# pmtiles2mbtiles

A simple Python script to convert [PMTiles](https://protomaps.com/docs/pmtiles) archives to [MBTiles](https://github.com/mapbox/mbtiles-spec) (SQLite) format, preserving all metadata and correctly converting tile coordinates between the two schemes.


## Features

- Converts all PMTiles in a folder
- Auto-detects tile format from the PMTiles header (`png`, `jpeg`, `webp`, `avif`, `pbf`)
- Copies all embedded metadata (name, description, attribution, bounds, zoom levels)
- Correctly flips tile Y coordinates from XYZ (PMTiles) to TMS (MBTiles)
- Output file is named automatically from the input filename
- Commits every 500 tiles so partial output is usable if interrupted
- Warns if the source contains vector (pbf) data that raster tools cannot use


## Requirements

- Python 3.8+
- [pmtiles](https://pypi.org/project/pmtiles/) Python library

Install the dependency:

```bash
pip install pmtiles
```


## Usage

Edit the last line of the script to point to your input file:

```python
pmtiles_to_mbtiles("your_file.pmtiles")
```

Then run:

```bash
python pmtiles2mbtiles.py
```

The output MBTiles file will be written to the same directory as the input, with the same base name:

```
Nepal_border.pmtiles  →  Nepal_border.mbtiles
```


## Example Output

```
Detected tile format: webp (raw: TileType.WEBP)
  Name:    Nepal_border
  Output:  Nepal_border.mbtiles
  Bounds:  80.947266,27.683528,88.264160,30.505484
  Zoom:    0 → 14
  500 tiles written...
  1000 tiles written...
  ...
Done — 8705 tiles written to Nepal_border.mbtiles
```


## Supported Tile Formats

| Format | Type   | GDAL/Raster compatible |
|--------|--------|------------------------|
| png    | Raster | ✅                      |
| jpeg   | Raster | ✅                      |
| webp   | Raster | ✅ (GDAL 3.4+)          |
| avif   | Raster | ⚠️ Limited              |
| pbf    | Vector | ❌                      |

> **Note:** WebP MBTiles support varies by application. If your tool does not render WebP tiles, you will need to transcode to PNG/JPEG using [Pillow](https://pillow.readthedocs.io/) as a post-processing step.


## Downstream Usage

Once converted, the MBTiles file can be used directly with GDAL:

```bash
# Inspect
gdalinfo Nepal_border.mbtiles

# Export to GeoTIFF
gdal_translate Nepal_border.mbtiles Nepal_border.tif -of GTiff

# Export to Cloud-Optimised GeoTIFF
gdal_translate Nepal_border.mbtiles Nepal_border.tif -of COG -co COMPRESS=DEFLATE
```


## Coordinate System Note

PMTiles stores tiles in **XYZ** order (origin top-left), while MBTiles uses **TMS** order (origin bottom-left). This script automatically flips the Y axis per zoom level during conversion:

```python
flipped_y = (1 << z) - 1 - y
```


## Limitations

- PMTiles → MBTiles only. For MBTiles → PMTiles use the official [go-pmtiles](https://github.com/protomaps/go-pmtiles) CLI tool.
- No tile transcoding (WebP → PNG etc.) — the tile data is copied as-is.
- Tested with PMTiles spec version 3.


## Related Tools

- [go-pmtiles](https://github.com/protomaps/go-pmtiles) — official PMTiles CLI (Go)
- [pmtiles Python library](https://pypi.org/project/pmtiles/) — PMTiles reader/writer
- [GDAL](https://gdal.org/) — geospatial raster/vector conversion
- [MapTiler](https://www.maptiler.com/) — tile hosting and conversion


## Licence

MIT
