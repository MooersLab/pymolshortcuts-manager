# Makefile for pymolshortcuts_manager test suite
# 283 tests across 39 test classes (as of 2026-08-02)
#
# Usage:
#   make test      – run the full suite
#   make verbose   – one line per test
#   make quiet     – dot per test
#   make coverage  – HTML coverage report
#   make single T=TestRAGEngine::test_cosine_similarity_identical
#   make failed    – re-run only previously failed tests
#   make lint      – flake8 on plugin source
#   make mcp       – smoke test the companion MCP server over stdio
#   make cc-license – download the official CC BY 4.0 legal code
#   make clean     – remove caches and bytecode
#   make help      – list targets

PLUGIN   = pymolshortcuts_manager.py
MCP      = pymolshortcuts_mcp.py
TESTS    = test_pymolshortcuts_manager.py
PYTEST   = python -m pytest
PYTHON   = python

.PHONY: test verbose quiet coverage single failed lint mcp cc-license clean help

test:
	$(PYTEST) $(TESTS)

verbose:
	$(PYTEST) $(TESTS) -v

quiet:
	$(PYTEST) $(TESTS) -q

coverage:
	$(PYTEST) $(TESTS) --cov=pymolshortcuts_manager --cov-report=html
	@echo "Open htmlcov/index.html to view the report."

single:
	$(PYTEST) $(TESTS) -v -k "$(T)"

failed:
	$(PYTEST) $(TESTS) --lf

lint:
	python -m flake8 $(PLUGIN) $(MCP) --max-line-length=120 --ignore=E501,W503,W291,W293

mcp:
	@printf '%s\n' \
	  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}' \
	  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
	  | $(PYTHON) $(MCP)

# Vendor the authoritative CC BY 4.0 text that covers docs/images.
# The file is downloaded rather than committed by hand, so the copy in the
# repository is byte-for-byte what Creative Commons publishes.
cc-license:
	curl -fsSL https://creativecommons.org/licenses/by/4.0/legalcode.txt \
	  -o LICENSE-CC-BY-4.0.txt
	@echo "Wrote LICENSE-CC-BY-4.0.txt. Commit it, then the notice in"
	@echo "docs/images/LICENSE points at a local copy of the legal code."

clean:
	rm -rf __pycache__ .pytest_cache htmlcov .coverage
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -type d -exec rm -rf {} +

help:
	@echo "Targets:"
	@echo "  test      Run all tests"
	@echo "  verbose   Verbose output (one line per test)"
	@echo "  quiet     Minimal output (dot per test)"
	@echo "  coverage  HTML coverage report"
	@echo "  single    Run a single test: make single T=TestName::test_method"
	@echo "  failed    Re-run only previously failed tests"
	@echo "  lint      Lint the plugin and MCP sources"
	@echo "  mcp       Smoke test the companion MCP server"
	@echo "  cc-license Download the official CC BY 4.0 legal code"
	@echo "  clean     Remove caches and bytecode"
	@echo "  help      Show this message"