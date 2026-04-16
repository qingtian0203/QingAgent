with open("qingagent/server/app.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

out = []
in_script = False
for line in lines:
    out.append(line)

print("Check lines length:", len(lines))
