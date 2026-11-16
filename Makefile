PYTHON ?= .venv/bin/python

.PHONY: install demo test app bench

install:
	$(PYTHON) -m pip install -q -r requirements.txt

demo:
	$(PYTHON) -m src.replay

test:
	$(PYTHON) -m pytest -q

app:
	$(PYTHON) -m streamlit run app.py

bench:
	$(PYTHON) bench.py
