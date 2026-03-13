import os
import sqlite3
from pmtiles.reader import Reader, MmapSource, all_tiles

# Mapping from PMTiles enum name to MBTiles format string.
# The pmtiles library returns a TileType enum (e.g. TileType.WEBP)
# rather than a plain integer, so we key off the enum's .name attribute.
TILE_TYPE_MAP = {
    "UNKNOWN": "unknown",
    "MVT":     "pbf",       # Mapbox Vector Tiles (vector data)
    "PNG":     "png",
    "JPEG":    "jpeg",
    "WEBP":    "webp",
    "AVIF":    "avif",
}

def get_tile_format(tile_type):
    """
    Resolve the tile format string from the header's tile_type field.
    The pmtiles library may return either a TileType enum object or a
    raw integer depending on version, so we handle both cases.
    """
    # Use the enum's .name attribute if available (e.g. TileType.WEBP → "WEBP"),
    # otherwise fall back to converting the raw integer to a string.
    key = tile_type.name if hasattr(tile_type, "name") else str(tile_type)
    return TILE_TYPE_MAP.get(key, "unknown")


def pmtiles_to_mbtiles(input_path):
    """
    Convert a PMTiles file to an MBTiles (SQLite) file.
    The output file is written to the same directory as the input,
    with the same base name and a .mbtiles extension.
    """

    # Derive output path from input — e.g. Nepal_border.pmtiles → Nepal_border.mbtiles
    output_path = os.path.splitext(input_path)[0] + ".mbtiles"

    # Remove any existing output file so we start with a clean slate
    if os.path.exists(output_path):
        os.remove(output_path)

    with open(input_path, "rb") as f:
        # MmapSource wraps the file for efficient random-access reads,
        # which PMTiles requires due to its non-sequential tile layout.
        source = MmapSource(f)
        reader = Reader(source)

        # The header contains format info, bounds, zoom levels, and metadata
        header = reader.header()

        # --- Tile format detection ---
        tile_type_id = header.get("tile_type", 0)
        tile_format  = get_tile_format(tile_type_id)
        print(f"Detected tile format: {tile_format} (raw: {tile_type_id})")

        if tile_format == "unknown":
            raise ValueError(f"Unrecognised tile type '{tile_type_id}' — cannot proceed.")

        if tile_format == "pbf":
            # PBF/MVT is vector, not raster — MBTiles will store it fine but
            # GDAL and other raster tools will not be able to consume it.
            print("WARNING: pbf is vector data — MBTiles will store it correctly but "
                  "GDAL/raster tools won't be able to use it.")

        # --- Extract metadata from header ---
        # Fall back to the filename stem if no name is embedded in the file
        name        = header.get("name", os.path.splitext(os.path.basename(input_path))[0])
        description = header.get("description", "")
        attribution = header.get("attribution", "")
        version     = str(header.get("version", "1"))
        map_type    = header.get("type", "baselayer")

        # Bounds and center are stored as fixed-point integers (value × 1e7) in the header
        min_lon     = header.get("min_lon_e7", 0) / 1e7
        min_lat     = header.get("min_lat_e7", 0) / 1e7
        max_lon     = header.get("max_lon_e7", 0) / 1e7
        max_lat     = header.get("max_lat_e7", 0) / 1e7
        center_lon  = header.get("center_lon_e7", 0) / 1e7
        center_lat  = header.get("center_lat_e7", 0) / 1e7
        center_zoom = header.get("center_zoom", 7)
        min_zoom    = header.get("min_zoom", 0)
        max_zoom    = header.get("max_zoom", 14)

        print(f"  Name:    {name}")
        print(f"  Output:  {output_path}")
        print(f"  Bounds:  {min_lon},{min_lat},{max_lon},{max_lat}")
        print(f"  Zoom:    {min_zoom} → {max_zoom}")

        # --- Create MBTiles SQLite structure ---
        # MBTiles spec requires exactly these two tables and this index
        con = sqlite3.connect(output_path)
        cur = con.cursor()

        cur.executescript("""
            CREATE TABLE metadata (name TEXT, value TEXT);
            CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB);
            CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row);
        """)

        # Write all metadata key/value pairs into the metadata table
        metadata = [
            ("name",        name),
            ("format",      tile_format),
            ("description", description),
            ("attribution", attribution),
            ("type",        map_type),
            ("version",     version),
            ("bounds",      f"{min_lon},{min_lat},{max_lon},{max_lat}"),
            ("center",      f"{center_lon},{center_lat},{center_zoom}"),
            ("minzoom",     str(min_zoom)),
            ("maxzoom",     str(max_zoom)),
        ]
        cur.executemany("INSERT INTO metadata VALUES (?,?)", metadata)

        # --- Copy tiles ---
        count = 0
        for zxy, data in all_tiles(source):
            z, x, y = zxy

            # PMTiles uses XYZ (origin top-left) but MBTiles uses TMS (origin bottom-left).
            # Flip the y axis per zoom level to convert between the two schemes.
            flipped_y = (1 << z) - 1 - y

            cur.execute("INSERT OR REPLACE INTO tiles VALUES (?,?,?,?)",
                        (z, x, flipped_y, sqlite3.Binary(data)))
            count += 1

            # Commit progress periodically so the file is usable if interrupted
            if count % 500 == 0:
                con.commit()
                print(f"  {count} tiles written...")

        # Final commit and close
        con.commit()
        con.close()
        print(f"Done — {count} tiles written to {output_path}")


pmtiles_to_mbtiles("Nepal_border.pmtiles")
