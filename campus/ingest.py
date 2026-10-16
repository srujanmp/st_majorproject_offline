"""Turning uploaded files into knowledge entries."""
import csv
import io

MAX_ROWS = 2000


class IngestError(Exception):
    pass


def decode(data: bytes) -> str:
    # Excel on Windows often saves CSV in cp1252 rather than UTF-8.
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise IngestError("Could not read the file's text. Save it as UTF-8.")


def parse_csv(text: str, filename: str) -> list[dict]:
    """Return a list of {"title", "content"} from CSV text.

    * A CSV with `title` and `content` columns gives one entry per row.
    * Any other CSV (a timetable, a staff list...) also works: each row becomes
      "Column: value. Column: value." titled with the file name and row number.
    """
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise IngestError("The CSV is empty.")
    columns = {(c or "").strip().lower(): c for c in reader.fieldnames}
    simple = "title" in columns and "content" in columns
    base = filename.rsplit(".", 1)[0] or "CSV"

    entries = []
    for n, row in enumerate(reader, start=1):
        if n > MAX_ROWS:
            raise IngestError(f"Too many rows. The limit is {MAX_ROWS} per file.")
        if simple:
            title = (row.get(columns["title"]) or "").strip()
            content = (row.get(columns["content"]) or "").strip()
        else:
            parts = [
                f"{(col or '').strip()}: {(val or '').strip()}"
                for col, val in row.items()
                if col and isinstance(val, str) and val.strip()
            ]
            title, content = f"{base} - row {n}", ". ".join(parts)
        if title and content:
            entries.append({"title": title[:200], "content": content})

    if not entries:
        raise IngestError("No usable rows found in the CSV.")
    return entries


def parse_file(data: bytes, filename: str) -> list[dict]:
    """CSV files give one entry per row; .txt and .md files give one entry each."""
    name = filename or "upload.txt"
    text = decode(data)
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension == "csv":
        return parse_csv(text, name)
    if extension in ("txt", "md"):
        content = text.strip()
        if not content:
            raise IngestError("The file is empty.")
        return [{"title": name.rsplit(".", 1)[0][:200], "content": content}]
    raise IngestError("Upload a .csv, .txt or .md file.")
