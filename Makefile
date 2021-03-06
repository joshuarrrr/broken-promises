# Makefile -- Broken Promises

WEBAPP     = $(wildcard */webapp.py)
WORKERS    = Scripts/workers
TEST       = Tests/all.py

run:
	mongod&
	$(WORKERS)&
	. `pwd`/.env ; python $(WEBAPP)

install:
	virtualenv venv --no-site-packages --distribute --prompt=BrokenPromises
	. `pwd`/.env ; pip install -r requirements.txt

test:
	. `pwd`/.env ; python -m unittest discover -s "brokenpromises" -p '*.py' -v

# EOF
