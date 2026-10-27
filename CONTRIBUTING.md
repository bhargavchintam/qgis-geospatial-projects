# Contributing

Thanks for your interest. Bug reports, fixes and new pipelines are all welcome. For a big change, please open an issue first so we can agree on the approach.

## Run the tests

Each project folder is self-contained. It has its own `requirements.txt`, `pytest.ini` and `tests/` folder, so run the tests from inside the project folder. Python 3.10 or newer works (CI uses 3.11).

```bash
cd flood-risk-assessment          # or any other project folder
pip install -r requirements.txt
python -m pytest tests -q
```

CI (`.github/workflows/ci.yml`) runs these steps for all six projects on every push and pull request to `main`. Please run them yourself before you open a pull request:

```bash
python -m pytest tests -q                    # unit and end-to-end tests
python demo.py --size 80 --out results/ci    # the demo runs end to end on a small grid
python -m py_compile qgis/processing/*.py    # the QGIS Processing script compiles
```

CI also checks that every `qgis/styles/*.qml` file is valid XML and that `app.py` parses.

Note: `demo.py` rewrites `docs/figures/` and `docs/map.html`. If you did not mean to change them, undo it with `git checkout -- docs` before you commit. If you did mean to change them, run the demo with the default size and seed so the numbers in the READMEs still match.

## Add a new pipeline

1. Create a new folder at the repo root and copy the layout of an existing project:

   ```
   my-new-project/
   ├── README.md          what it does, results, method, real data sources
   ├── LICENSE            MIT, same as the root
   ├── demo.py            one-command demo; CI calls it with --size and --out
   ├── app.py             Streamlit dashboard
   ├── config.yaml        all parameters and data paths
   ├── requirements.txt
   ├── pytest.ini
   ├── src/               pipeline.py, synthetic_data.py, visualize.py and other modules
   ├── tests/             unit tests and a small end-to-end test_demo.py
   ├── qgis/styles/       .qml styles for the output layers
   ├── qgis/processing/   a QgsProcessingAlgorithm script for the core method
   └── docs/              figures/00_hero.png and map.html, written by demo.py
   ```

2. Include a synthetic data generator, so the demo runs with no downloads or accounts. Keep the end-to-end test small and fast, and write its outputs to a temporary folder (see any existing `tests/test_demo.py`).
3. Add the folder name to the `matrix.project` list in `.github/workflows/ci.yml`.
4. Add the project to the tables in the root `README.md` and add a card for it in `index.html`. Use the numbers that your `demo.py` prints.

## License

This repo is under the MIT license (see [LICENSE](LICENSE)). By sending a contribution, you agree that it is released under the same MIT license.
