import pathlib

f = pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/app/main.py').read_text(encoding='utf-8')

# Find _role_scenario_reply function definition  
idx = f.find('def _role_scenario_reply')
chunk = f[idx:idx+5000]
pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/tmp_role_scenario_fn.txt').write_text(chunk, encoding='utf-8')

# Find all "sibling" references
occurrences = []
start = 0
while True:
    idx2 = f.find('sibling', start)
    if idx2 < 0:
        break
    occurrences.append(idx2)
    start = idx2 + 1

sibling_chunks = []
for occ in occurrences:
    sibling_chunks.append(f'=== at {occ} ===\n' + f[max(0,occ-50):occ+200])
    
pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/tmp_sibling_all.txt').write_text('\n\n'.join(sibling_chunks), encoding='utf-8')

print(f'Found {len(occurrences)} occurrences of sibling')

