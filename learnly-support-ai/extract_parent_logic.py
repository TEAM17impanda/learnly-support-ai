import pathlib

f = pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/app/main.py').read_text(encoding='utf-8')

# Find _payment_escalate
idx = f.find('def _payment_escalate')
chunk = f[idx:idx+4000]
pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/tmp_payment_esc2.txt').write_text(chunk, encoding='utf-8')

# Find _continue_pending
idx2 = f.find('def _continue_pending')
chunk2 = f[idx2:idx2+2000]
pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/tmp_continue_pending.txt').write_text(chunk2, encoding='utf-8')

# Find RoleChatMessage model
idx3 = f.find('RoleChatMessage')
chunk3 = f[idx3:idx3+500]
pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/tmp_role_chat_model.txt').write_text(chunk3, encoding='utf-8')

print('done')

