PYTHON ?= python

.PHONY: install help state-init state-status discover-topics list-planned-topics show-topic build-fact-pack generate-brief generate-article build-blog-package generate-cover-image show-image-meta qa-approve qa-status publish-topic publish-status

install:
	$(PYTHON) -m pip install -e .

help:
	$(PYTHON) -m blogspot_automation.cli.main --help

state-init:
	$(PYTHON) -m blogspot_automation.cli.main state init

state-status:
	$(PYTHON) -m blogspot_automation.cli.main state status

discover-topics:
	$(PYTHON) -m blogspot_automation.cli.main discover-topics

list-planned-topics:
	$(PYTHON) -m blogspot_automation.cli.main list-planned-topics

show-topic:
	$(PYTHON) -m blogspot_automation.cli.main show-topic --topic-id $(TOPIC_ID)

build-fact-pack:
	$(PYTHON) -m blogspot_automation.cli.main build-fact-pack --topic-id $(TOPIC_ID)

generate-brief:
	$(PYTHON) -m blogspot_automation.cli.main generate-brief --topic-id $(TOPIC_ID)

generate-article:
	$(PYTHON) -m blogspot_automation.cli.main generate-article --topic-id $(TOPIC_ID)

build-blog-package:
	$(PYTHON) -m blogspot_automation.cli.main build-blog-package --topic-id $(TOPIC_ID)

generate-cover-image:
	$(PYTHON) -m blogspot_automation.cli.main generate-cover-image --topic-id $(TOPIC_ID)

show-image-meta:
	$(PYTHON) -m blogspot_automation.cli.main show-image-meta --topic-id $(TOPIC_ID)

qa-approve:
	$(PYTHON) -m blogspot_automation.cli.main qa-approve --topic-id $(TOPIC_ID)

qa-status:
	$(PYTHON) -m blogspot_automation.cli.main qa-status --topic-id $(TOPIC_ID)

publish-topic:
	$(PYTHON) -m blogspot_automation.cli.main publish-topic --topic-id $(TOPIC_ID)

publish-status:
	$(PYTHON) -m blogspot_automation.cli.main publish-status --topic-id $(TOPIC_ID)
