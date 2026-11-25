"""Build a clean browser bundle from the committed synthetic source."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from src import database as storage, etl, train_model
from src.config import ROOT


def write_explorer(destination, snapshot):
    rows = snapshot["rows"]
    if len(rows) > 1000:
        chunk_size = 128
        columns = snapshot["columns"]
        id_col, service_col, priority_col = map(columns.index, ["incident_id", "affected_service", "priority"])
        services = sorted({row[service_col] for row in rows})
        priorities = sorted({row[priority_col] for row in rows})
        service_index = {value: i for i, value in enumerate(services)}
        priority_index = {value: i for i, value in enumerate(priorities)}
        index = [[row[id_col], service_index[row[service_col]], priority_index[row[priority_col]]]
                 for row in rows]
        details = destination / "details"
        details.mkdir(exist_ok=True)
        chunks = []
        for offset in range(0, len(rows), chunk_size):
            payload = json.dumps(rows[offset:offset + chunk_size], separators=(",", ":"), allow_nan=False).encode()
            name = sha256(payload).hexdigest()[:24] + ".json"
            (details / name).write_bytes(payload)
            chunks.append("details/" + name)
        snapshot = {**snapshot, "rows": rows[:6], "index": index, "services": services,
                    "priorities": priorities, "chunks": chunks, "chunkSize": chunk_size}
    template = (ROOT / "public_demo/index.html").read_text(encoding="utf-8")
    data = json.dumps(snapshot, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    (destination / "index.html").write_text(template.replace("SNAPSHOT_JSON", data), encoding="utf-8")


def build(destination):
    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as temporary:
        staging = Path(temporary)
        database = staging / "data/processed/signal.db"
        model = staging / "models/sla_model.joblib"
        etl.run_pipeline("data/raw/incidents_raw.csv", database,
                         database.with_suffix(".csv"), staging / "rejected.csv")
        train_model.train(database, model, model.with_name("metrics.json"))
        columns = ["incident_id", "affected_service", "category", "priority", "status",
                   "assignment_group", "created_at", "sla_target_minutes", "resolution_time_minutes",
                   "sla_breached", "breach_probability", "risk_level"]
        incidents = storage.read_incidents(database).sort_values(
            ["breach_probability", "incident_id"], ascending=[False, True])
        snapshot = {"metrics": storage.kpi_summary(database), "columns": columns,
                    "rows": json.loads(incidents[columns].to_json(orient="values"))}
        write_explorer(destination, snapshot)
        with ZipFile(destination / "demo.zip", "w", ZIP_DEFLATED) as archive:
            for file in [ROOT / "app.py", *sorted((ROOT / "src").glob("*.py")),
                         *sorted((ROOT / "assets").glob("*.svg"))]:
                archive.write(file, file.relative_to(ROOT))
            for file in [database, model, model.with_name("metrics.json")]:
                archive.write(file, file.relative_to(staging))
    for name in ["workspace.html", "demo.css", "demo.js"]:
        shutil.copyfile(ROOT / "public_demo" / name, destination / name)
    shutil.copyfile(ROOT / "assets/okai-wordmark.svg", destination / "okai-wordmark.svg")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    build(parser.parse_args().destination)
