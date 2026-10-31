import pathlib

f = pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/app/main.py').read_text(encoding='utf-8')

# Find role-chat section
idx = f.find('role-chat')
# Go back a bit to get context
start = max(0, idx - 50)
chunk = f[start:start+5000]
pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/tmp_role_chat.txt').write_text(chunk, encoding='utf-8')
print('done, length:', len(chunk))

