import os
import sys
import glob
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
    Convert a single PMTiles file to an MBTiles (SQLite) file.
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
        print(f"  Detected tile format: {tile_format} (raw: {tile_type_id})")

        if tile_format == "unknown":
            raise ValueError(f"Unrecognised tile type '{tile_type_id}' — cannot proceed.")

        if tile_format == "pbf":
            # PBF/MVT is vector, not raster — MBTiles will store it fine but
            # GDAL and other raster tools will not be able to consume it.
            print("  WARNING: pbf is vector data — MBTiles will store it correctly but "
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
        print(f"  Done — {count} tiles written to {output_path}")

    return output_path


def convert_folder(folder_path):
    """
    Convert all PMTiles files in a folder to MBTiles.
    Skips files that already have a matching .mbtiles output.
    Reports a summary of successes and failures at the end.
    """
    # Find all .pmtiles files in the folder (non-recursive)
    pattern = os.path.join(folder_path, "*.pmtiles")
    files   = sorted(glob.glob(pattern))

    if not files:
        print(f"No .pmtiles files found in: {folder_path}")
        return

    print(f"Found {len(files)} PMTiles file(s) in: {folder_path}\n")

    succeeded = []
    failed    = []
    skipped   = []

    for i, input_path in enumerate(files, 1):
        output_path = os.path.splitext(input_path)[0] + ".mbtiles"
        filename    = os.path.basename(input_path)

        print(f"[{i}/{len(files)}] {filename}")

        # Skip if output already exists — remove this block to always overwrite
        if os.path.exists(output_path):
            print(f"  Skipping — {os.path.basename(output_path)} already exists.")
            skipped.append(filename)
            print()
            continue

        try:
            pmtiles_to_mbtiles(input_path)
            succeeded.append(filename)
        except Exception as e:
            # Log the error but continue processing remaining files
            print(f"  ERROR: {e}")
            failed.append((filename, str(e)))

        print()

    # --- Summary ---
    print("=" * 60)
    print(f"Conversion complete.")
    print(f"  Succeeded : {len(succeeded)}")
    print(f"  Skipped   : {len(skipped)}")
    print(f"  Failed    : {len(failed)}")

    if failed:
        print("\nFailed files:")
        for name, error in failed:
            print(f"  {name}: {error}")


# --- Entry point ---
# Run against a single file or a folder, based on what is provided.
# Usage:
#   python pmtiles2mbtiles.py                        ← converts current folder
#   python pmtiles2mbtiles.py myfile.pmtiles         ← converts single file
#   python pmtiles2mbtiles.py "C:\path\to\folder"   ← converts all in folder

if __name__ == "__main__":
    if len(sys.argv) == 1:
        # No argument — convert all PMTiles in the current working directory
        convert_folder(".")

    elif len(sys.argv) == 2:
        target = sys.argv[1]

        if os.path.isdir(target):
            # Argument is a folder — batch convert
            convert_folder(target)

        elif os.path.isfile(target) and target.endswith(".pmtiles"):
            # Argument is a single PMTiles file
            pmtiles_to_mbtiles(target)

        else:
            print(f"Error: '{target}' is not a .pmtiles file or a valid folder.")
            sys.exit(1)

    else:
        print("Usage: python pmtiles2mbtiles.py [file.pmtiles | folder]")
        sys.exit(1)
