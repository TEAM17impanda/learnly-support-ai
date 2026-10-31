import pathlib

f = pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/app/main.py').read_text(encoding='utf-8')

# Find _detect_role_scenario to understand what scenarios are registered
idx = f.find('_detect_role_scenario')
chunk = f[idx:idx+4000]
pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/tmp_scenario.txt').write_text(chunk, encoding='utf-8')

# Also find _role_scenario_reply
idx2 = f.find('_role_scenario_reply')
chunk2 = f[idx2:idx2+4000]
pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/tmp_scenario_reply.txt').write_text(chunk2, encoding='utf-8')

print('done')

