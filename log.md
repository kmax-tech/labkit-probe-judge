12:59:00 · read · TASK.md (41 lines)
12:59:00 · run · git checkout -b probe-judge; ls area
12:59:03 · read · area README, PROTOCOL, scripts
12:59:08 · run · protocol-check --contract
12:59:12 · read · 00_prepare.py, 02_analyze.py, tests/
12:59:22 · edit · 00_prepare.py + 01_measure.py TODOs (paths, ANSWERS, prompts)
12:59:26 · run · 00_prepare.py (write prepared data)
12:59:35 · edit · protocol-fill: registration fields
12:59:38 · run · 01_measure.py --show 2 (render check)
12:59:38 · run · code-check area
12:59:41 · run · 01_measure.py --probe (instrument check, real calls)
13:00:25 · edit · test: paste probe parser cases; protocol check fields
13:00:25 · run · code-check + pytest + preflight
13:00:30 · run · git commit (registration, scripts, test)
13:00:30 · run · labkit-audit --mode preflight
13:12:44 · read · audit findings toml
13:12:56 · edit · fix audit findings: denominators, float compare, parser normalisation, gold check, promise sentences
13:13:03 · edit · audit toml statuses
13:13:12 · run · protocol head: audit line; labkit-init exp --report
13:13:21 · edit · protocol-fill † fields, frozen = true
13:13:26 · gate · scope sha changed after audit; restamp (fixes decided) instead of re-audit
13:13:29 · run · git commit (frozen); runlog start -- measure
13:13:32 · run · runlog . --wait
13:14:07 · run · protocol-fill --from-run; finalize
13:14:17 · edit · protocol write-back fields
13:14:17 · run · commit output/runs, finalize
13:14:23 · run · labkit-audit --mode analysis (background)
13:14:23 · edit · README placeholders
13:21:24 · edit · fix analysis-audit findings in protocol, decide toml
13:21:35 · run · final commit incl. log.md, push probe-judge
