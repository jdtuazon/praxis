.PHONY: install test demo bench serve memory clean

install:        ## install dependencies (use a venv)
	pip install -r requirements.txt

test:           ## run the full offline test suite
	pytest

demo:           ## run the 3-instruction demo (offline, no keys)
	python -m praxis demo --offline

bench:          ## reproduce the learning before/after numbers
	python -m praxis bench

serve:          ## launch the web dashboard
	python -m praxis serve

memory:         ## inspect persistent memory
	python -m praxis memory show

clean:          ## remove caches + the local memory DB
	rm -rf .pytest_cache **/__pycache__ .praxis
