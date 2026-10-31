import pathlib

# Read full teacher_agent.py
ta = pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/app/teacher_agent.py').read_text(encoding='utf-8')
pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/tmp_ta_full.txt').write_text(ta, encoding='utf-8')

# Read full main.py parent sections
main = pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/app/main.py').read_text(encoding='utf-8')

# Extract from _payment_start to end of _continue_pending
start = main.find('# ---------- сценарій батьків')
end = main.find('\ndef _role_scenario_reply')
chunk = main[start:end]
pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/tmp_parent_main.txt').write_text(chunk, encoding='utf-8')

# Also get _create_escalation signature
idx = main.find('def _create_escalation')
chunk2 = main[idx:idx+1500]
pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/tmp_create_esc.txt').write_text(chunk2, encoding='utf-8')

print('done, lengths:', len(ta), len(chunk), len(chunk2))

