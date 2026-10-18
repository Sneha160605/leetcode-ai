test:      ; cd backend && python3 -m unittest discover -s tests -t . && python3 -m judge.selftest && LANGUAGE=javascript python3 -m judge.selftest
sim:       ; python3 loadtest/queue_sim.py 60 4
images:    ; for l in python javascript; do docker build --build-arg LANGUAGE=$$l -t judge-$$l backend; done
synth:     ; cd infra && npm install && npx cdk synth
deploy:    ; cd infra && npx cdk deploy --all -c stableTag=$(TAG)
