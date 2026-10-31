import pathlib, re

f = pathlib.Path('D:/моє/learnly-support-ai/learnly-support-ai/app/main.py').read_text(encoding='utf-8')
routes = re.findall(r'@app\.(get|post|put|delete)\(["\']([^"\']+)["\']', f)
for method, path in routes:
    print(f"{method.upper()} {path}")

