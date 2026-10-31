import pathlib

f = pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/app/main.py').read_text(encoding='utf-8')

# Find ROLE_SCENARIOS definition
idx = f.find('ROLE_SCENARIOS')
chunk = f[idx:idx+3000]
pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/tmp_role_scenarios.txt').write_text(chunk, encoding='utf-8')

# Find _payment_escalate and sibling scenario
idx2 = f.find('_payment_escalate')
chunk2 = f[idx2:idx2+3000]
pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/tmp_payment_esc.txt').write_text(chunk2, encoding='utf-8')

# Find sibling scenario (_sibling_start)
idx3 = f.find('_sibling')
chunk3 = f[idx3:idx3+3000]
pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/tmp_sibling.txt').write_text(chunk3, encoding='utf-8')

print('done')

