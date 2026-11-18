.PHONY: check check-security
check:
	python scripts/check.py
check-security:
	python scripts/check.py --security
