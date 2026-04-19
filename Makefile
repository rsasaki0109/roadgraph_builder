# Run from repository root.
.PHONY: install test bench demo tune doctor release-bundle docs

install:
	python3 -m pip install -e ".[dev]"

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest

bench:
	python scripts/run_benchmarks.py

demo:
	./scripts/run_demo_bundle.sh

tune:
	./scripts/run_tuning_bundle.sh

doctor:
	roadgraph_builder doctor

release-bundle:
	bash scripts/build_release_bundle.sh

# pdoc-based API docs → build/docs/roadgraph_builder/. Requires the `[docs]`
# extra (`pip install -e ".[docs]"`).
docs:
	pdoc -o build/docs roadgraph_builder
	@echo "Open build/docs/roadgraph_builder.html in a browser."
