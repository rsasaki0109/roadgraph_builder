# Run from repository root.
.PHONY: install test demo tune doctor release-bundle

install:
	python3 -m pip install -e ".[dev]"

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest

demo:
	./scripts/run_demo_bundle.sh

tune:
	./scripts/run_tuning_bundle.sh

doctor:
	roadgraph_builder doctor

release-bundle:
	bash scripts/build_release_bundle.sh
