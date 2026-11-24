"""Build a clean browser bundle from the committed synthetic source."""
import argparse
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from src import etl, train_model
from src.config import ROOT


def build(destination):
    destination.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as temporary:
        staging = Path(temporary)
        database = staging / "data/processed/signal.db"
        model = staging / "models/sla_model.joblib"
        etl.run_pipeline("data/raw/incidents_raw.csv", database,
                         database.with_suffix(".csv"), staging / "rejected.csv")
        train_model.train(database, model, model.with_name("metrics.json"))
        with ZipFile(destination / "demo.zip", "w", ZIP_DEFLATED) as archive:
            for file in [ROOT / "app.py", *sorted((ROOT / "src").glob("*.py")),
                         *sorted((ROOT / "assets").glob("*.svg"))]:
                archive.write(file, file.relative_to(ROOT))
            for file in [database, model, model.with_name("metrics.json")]:
                archive.write(file, file.relative_to(staging))
    shutil.copyfile(ROOT / "public_demo/index.html", destination / "index.html")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    build(parser.parse_args().destination)
